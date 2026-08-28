"""Queries only. Never commits -- the service owns the transaction."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from pigrocrm.core.gmail.models import GoogleAccount, GoogleOAuthState


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
