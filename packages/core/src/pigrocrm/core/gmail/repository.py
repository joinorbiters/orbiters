"""Queries only. Never commits -- the service owns the transaction."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.gmail.models import (
    GmailMessage,
    GmailMessageLink,
    GoogleAccount,
    GoogleOAuthState,
)
from pigrocrm.core.gmail.roster import EntityRef


class GmailRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def account_for_user(self, user_id: UUID) -> GoogleAccount | None:
        return self.session.execute(
            select(GoogleAccount).where(GoogleAccount.user_id == user_id)
        ).scalar_one_or_none()

    def account(self, account_id: UUID) -> GoogleAccount | None:
        return self.session.get(GoogleAccount, account_id)

    def add_state(self, state: GoogleOAuthState) -> GoogleOAuthState:
        self.session.add(state)
        self.session.flush()
        return state

    def consume_state(self, jti: str, now: datetime) -> GoogleOAuthState | None:
        """Marks the row consumed and returns it, or returns `None` if it does not
        exist, has expired, or was already consumed.

        One statement, deliberately: a conditional `UPDATE ... WHERE consumed_at IS
        NULL ... RETURNING`. Postgres serialises two concurrent callbacks carrying the
        same jti on the row lock, and the loser re-evaluates its `WHERE` against the
        winner's committed row, finds `consumed_at` no longer NULL and updates nothing.
        `test_gmail_models.py` proves that with two real connections and a barrier --
        drop the predicate and it reports `[1, 1]` instead of `[0, 1]`.

        A read-then-write pair over the same column would pass every single-threaded
        test and hand two callbacks the same authorisation code.
        """
        return self.session.execute(
            update(GoogleOAuthState)
            .where(
                GoogleOAuthState.jti == jti,
                GoogleOAuthState.consumed_at.is_(None),
                GoogleOAuthState.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(GoogleOAuthState)
        ).scalar_one_or_none()

    def prune_states(self, now: datetime) -> int:
        """Called at the start of every sync. `refresh_tokens` has this same problem
        and, per residuo R8, no pruning at all -- this table does not repeat it.

        Expiry, not consumption, is the criterion: a consumed row is still evidence
        that a jti was used, and it has to outlive its own TTL or the single-use check
        above would start answering "unknown" instead of "already redeemed" for a
        replay that arrives seconds later.
        """
        deleted = self.session.execute(
            delete(GoogleOAuthState)
            .where(GoogleOAuthState.expires_at < now)
            .returning(GoogleOAuthState.id)
        )
        # `RETURNING` rather than `rowcount`: the DBAPI's row count is typed as
        # `Any`-free only on `CursorResult`, and this table is small and short-lived
        # by construction, so counting the returned ids costs nothing worth naming.
        return len(deleted.scalars().all())

    # --- messages --------------------------------------------------------------------

    def message_ids_present(self, account_id: UUID, gmail_ids: Sequence[str]) -> set[str]:
        """Which of these Gmail ids this account has already stored.

        One query per thread rather than one per message: a cycle re-reads a whole day
        of already-stored conversations by design, so the common case is a thread in
        which every message is known and the interesting number is how many round trips
        finding that out costs.
        """
        if not gmail_ids:
            return set()
        rows = (
            self.session.execute(
                select(GmailMessage.gmail_message_id).where(
                    GmailMessage.google_account_id == account_id,
                    GmailMessage.gmail_message_id.in_(list(gmail_ids)),
                )
            )
            .scalars()
            .all()
        )
        return set(rows)

    def add_message_if_absent(self, message: GmailMessage) -> bool:
        """Inserts, and answers `False` if the unique constraint refused it.

        The insert runs inside a SAVEPOINT, and that is the point of the method. A
        duplicate is expected -- the watermark's overlap produces them on every cycle --
        so it must cost exactly the failed statement and nothing else. Catching the
        `IntegrityError` and calling `Session.rollback()` instead would discard every
        message stored earlier in the same cycle, because the cycle commits once at the
        end: one duplicate in a thread of thirty would throw away the twenty-nine before
        it. `test_gmail_sync.py` proves that difference on a single connection, and the
        two-thread race proves why the constraint is needed at all.
        """
        try:
            with self.session.begin_nested():
                self.session.add(message)
                self.session.flush()
        except IntegrityError:
            return False
        return True

    def message_by_gmail_id(self, account_id: UUID, gmail_id: str) -> GmailMessage | None:
        return self.session.execute(
            select(GmailMessage).where(
                GmailMessage.google_account_id == account_id,
                GmailMessage.gmail_message_id == gmail_id,
            )
        ).scalar_one_or_none()

    def delete_messages_for(self, account_id: UUID) -> int:
        """Called only when the user explicitly chose to on disconnect. The
        `gmail_message_links` rows go with them by ON DELETE CASCADE.

        `RETURNING` and not `rowcount`, for the reason `prune_states` states: the
        DBAPI's row count is only typed on `CursorResult`. The count matters here --
        it is what the timeline entry records about an irreversible deletion -- so it
        has to come from somewhere the type system agrees exists.
        """
        deleted = self.session.execute(
            delete(GmailMessage)
            .where(GmailMessage.google_account_id == account_id)
            .returning(GmailMessage.id)
        )
        return len(deleted.scalars().all())

    # --- links -----------------------------------------------------------------------

    def add_link(self, message_id: UUID, ref: EntityRef) -> bool:
        """Files one message against one entity, and answers `False` when the triple
        already existed.

        Concurrency-safe by constraint and not by pre-check: two overlapping cycles both
        pass a `SELECT`, and only `uq_gmail_message_links_triple` can arbitrate. And, for
        the reason `add_message_if_absent` states at length, the refusal is absorbed by a
        SAVEPOINT rather than by `Session.rollback()`: a cycle commits once at the end,
        so a session-wide rollback here would discard every message and every link
        written earlier in the same cycle -- on the *expected* outcome of the watermark's
        overlap re-reading a conversation that is already filed.
        """
        try:
            with self.session.begin_nested():
                self.session.add(
                    GmailMessageLink(
                        gmail_message_id=message_id,
                        entity_type=ref.entity_type,
                        entity_id=ref.entity_id,
                    )
                )
                self.session.flush()
        except IntegrityError:
            return False
        return True

    def messages_for_entity(
        self, entity_type: str, entity_id: UUID, *, limit: int
    ) -> list[GmailMessage]:
        """Everything filed against one customer, person or deal.

        Ordered by thread and then by date, because the reader of a customer page is
        reading conversations rather than a flat mailbox: interleaving two threads by
        timestamp alone produces a page on which no exchange can be followed.
        """
        return list(
            self.session.execute(
                select(GmailMessage)
                .join(GmailMessageLink, GmailMessageLink.gmail_message_id == GmailMessage.id)
                .where(
                    GmailMessageLink.entity_type == entity_type,
                    GmailMessageLink.entity_id == entity_id,
                )
                .order_by(GmailMessage.gmail_thread_id, GmailMessage.internal_date)
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def last_inbound_from(
        self, account_id: UUID, addresses: Sequence[str], since: datetime
    ) -> GmailMessage | None:
        """The most recent inbound message from any of `addresses` after `since`.

        This is the signal Acme could not have had: from the moment the CRM reads the
        mail, the reminder candidate list can say "the client replied on 12 August".
        Chasing someone who has already replied is the mistake a CRM that does not read
        email cannot even notice it is making.

        Scoped to one account, because Gmail's message ids and the addresses in them
        belong to a mailbox: another user's correspondence must not answer this user's
        question about whether the client wrote back.
        """
        if not addresses:
            # Not merely an optimisation: an empty sequence would render as `IN ()`,
            # which Postgres refuses outright.
            return None
        return self.session.execute(
            select(GmailMessage)
            .where(
                GmailMessage.google_account_id == account_id,
                GmailMessage.direction == "inbound",
                GmailMessage.from_address.in_([address.strip().lower() for address in addresses]),
                GmailMessage.internal_date > since,
            )
            .order_by(GmailMessage.internal_date.desc())
            .limit(1)
        ).scalar_one_or_none()
