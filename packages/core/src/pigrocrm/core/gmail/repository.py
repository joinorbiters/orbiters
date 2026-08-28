"""Queries only. Never commits -- the service owns the transaction."""

import hashlib
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.gmail.models import (
    GmailKnownAddress,
    GmailMessage,
    GmailMessageLink,
    GoogleAccount,
    GoogleOAuthState,
)
from pigrocrm.core.gmail.roster import EntityRef

# An arbitrary but stable first key for `pg_try_advisory_lock(int, int)`, so this
# project's locks cannot collide with another application sharing the database. The
# two-integer form is used rather than the single bigint one precisely because it
# namespaces: hashing a UUID into 64 bits alone risks colliding with anything else that
# also hashes something into 64 bits.
SYNC_LOCK_NAMESPACE = 0x7091


def _lock_key(account_id: UUID) -> int:
    """A signed 32-bit integer derived from the account id. Postgres advisory-lock keys
    are `int4`, and passing an out-of-range value is an error rather than a truncation,
    so the 128 bits have to be folded into 32 somehow.

    Two ways of folding them are wrong here, and both look right:

    * **The leading bytes of the UUID.** Every primary key in this schema is a **uuid7**
      (`db/base.py`), whose first six bytes are a millisecond timestamp. The first four
      of them therefore only change once every 65 seconds, so every mailbox connected in
      the same minute would share a lock and one user's cron would silently suppress
      everyone else's sync. `test_gmail_lock.py` catches exactly that: two accounts made
      in the same test collide on the nose.
    * **`hash()`.** Python randomises the hash of `bytes` per process, so the API worker
      and the cron container would compute different keys for the same mailbox and the
      lock would not exist at all.

    A short blake2b digest has neither problem: it spreads uuid7's ordered bits over the
    whole range and it is the same number in every process, forever. A collision -- one
    in 2^32 per pair -- costs one user's sync answering "già in corso" and being picked
    up by the next cycle, which is why this is worth less than a lock table of its own.
    """
    return int.from_bytes(
        hashlib.blake2b(account_id.bytes, digest_size=4).digest(), "big", signed=True
    )


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

    # --- the per-mailbox sync lock ---------------------------------------------------

    def try_sync_lock(self, account_id: UUID) -> bool:
        """Non-blocking. A caller that does not get the lock must answer "already in
        progress" -- it must not wait, and it must not fail.

        Session-scoped and not `pg_try_advisory_xact_lock`, so the lock covers the whole
        cycle regardless of how the cycle chooses to commit. That is also why it has to
        be handed back explicitly: see `release_sync_lock`.
        """
        return bool(
            self.session.execute(
                text("SELECT pg_try_advisory_lock(:ns, :key)"),
                {"ns": SYNC_LOCK_NAMESPACE, "key": _lock_key(account_id)},
            ).scalar_one()
        )

    def release_sync_lock(self, account_id: UUID) -> None:
        """Hands the lock back on the connection that holds it.

        This must not be a statement that can fail. A session-level advisory lock
        outlives its transaction *and* its SQLAlchemy `Session`: the connection returns
        to the pool still holding it, and every later sync for that mailbox then answers
        "already running" for the life of the process -- indistinguishable from a hung
        job, and unfixable without a restart.

        The one way the unlock can fail is on a transaction Postgres has already
        aborted, which refuses every further statement until it is rolled back. Hence
        the retry, and hence the `rollback` -- which is not the wide one it looks like:
        the server threw that work away itself when it aborted, so there is nothing left
        to discard. Deliberately *not* pre-emptive. `Session.is_active` stays `True`
        after a failed raw `execute` (it only goes false on a failed flush), so a check
        before the fact would not fire, and rolling back unconditionally would throw
        away a healthy caller's uncommitted work for nothing.
        """
        try:
            self._advisory_unlock(account_id)
        except DBAPIError:
            self.session.rollback()
            self._advisory_unlock(account_id)

    def _advisory_unlock(self, account_id: UUID) -> None:
        self.session.execute(
            text("SELECT pg_advisory_unlock(:ns, :key)"),
            {"ns": SYNC_LOCK_NAMESPACE, "key": _lock_key(account_id)},
        )

    def sync_started_at(self, account_id: UUID) -> datetime | None:
        """When the last cycle that *committed* began, or `None` if none ever has.

        Read from the row rather than from an in-memory attribute, because it is asked
        on behalf of a run happening on another connection: that run has not published
        its own `last_sync_at` yet and cannot, so the honest answer is the last one that
        finished. It is what makes "già in corso da stamattina" possible to tell apart
        from "già in corso da quaranta secondi", which is the whole reason a caller who
        lost the lock is given a time at all.
        """
        return self.session.execute(
            select(GoogleAccount.last_sync_at).where(GoogleAccount.id == account_id)
        ).scalar_one_or_none()

    # --- the addresses this mailbox has already looked for ---------------------------

    def seen_addresses(self, account_id: UUID) -> set[str]:
        """The register the backfill is derived from: roster minus this is "new"."""
        return set(
            self.session.execute(
                select(GmailKnownAddress.address).where(
                    GmailKnownAddress.google_account_id == account_id
                )
            )
            .scalars()
            .all()
        )

    def remember_addresses(self, account_id: UUID, addresses: Sequence[str]) -> int:
        """Records that this mailbox has now been searched over these addresses, and
        answers how many of them were not already recorded.

        One `INSERT ... ON CONFLICT DO NOTHING`, and that is the point of the method. A
        duplicate is expected -- two cycles overlapping, or an explicit backfill on an
        address the automatic one had already covered -- so it must cost exactly nothing
        beyond the statement. Catching an `IntegrityError` and calling
        `Session.rollback()` instead would discard every message and every link stored
        earlier in the same cycle, because the cycle commits once at the end: that is the
        same defect `add_message_if_absent` documents at length, and it would fire here
        on the *expected* outcome rather than on a rare one.

        Not the SAVEPOINT loop that method uses, because this one needs no row back: the
        count comes from `RETURNING`, so the whole thing is a single round trip however
        long the roster is.
        """
        if not addresses:
            return 0
        unique = list(dict.fromkeys(address.strip().lower() for address in addresses if address))
        if not unique:
            return 0
        inserted = self.session.execute(
            pg_insert(GmailKnownAddress)
            .values([{"google_account_id": account_id, "address": address} for address in unique])
            .on_conflict_do_nothing(constraint="uq_gmail_known_addresses")
            .returning(GmailKnownAddress.id)
        )
        return len(inserted.scalars().all())

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

        This is the signal the previous system could not have had: from the moment the CRM reads the
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
