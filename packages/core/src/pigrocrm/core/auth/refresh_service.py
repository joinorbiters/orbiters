from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.auth.refresh_models import RefreshToken
from pigrocrm.core.auth.tokens import issue_refresh_token
from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed

# Every failure this service reports -- an unknown jti, an expired row, one already
# consumed -- reads identically. Same anti-enumeration discipline as
# UserService.authenticate's dummy hash and PatService.resolve's INVALID_TOKEN:
# whoever is holding a stolen or replayed refresh token must not be able to tell "this
# exact token is dead" apart from "this user's whole session family was just revoked."
INVALID_REFRESH_TOKEN = "sessione non valida o scaduta"


class RefreshTokenService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def issue(self, user_id: UUID, settings: Settings) -> str:
        """Creates the row this token's `jti` points at, then signs the token. Order
        matters only in that both must share the same `jti` and roughly the same
        expiry -- computed independently here and inside `issue_refresh_token`, a
        handful of microseconds apart, never far enough apart to matter."""
        jti = uuid4()
        token = issue_refresh_token(user_id, settings, jti=jti)
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
        self.session.add(RefreshToken(jti=jti, user_id=user_id, expires_at=expires_at))
        self.session.commit()
        return token

    def consume(self, jti: UUID, user_id: UUID) -> None:
        """Marks a refresh token used up so it can never be presented again. Reusing an
        already-consumed token is the standard signal that it was stolen: the
        legitimate user rotated past it, so whoever is presenting it now is not them.
        Rewarding that replay with a fresh pair of tokens would leave the thief inside,
        so the response is to revoke every other still-valid token this user holds,
        not just the one being replayed.

        `with_for_update()` locks the row for the rest of this transaction: without
        it, two concurrent calls on the same jti (a genuine replay -- an attacker and
        the legitimate user racing, or even just a retried request) can both read
        `consumed_at IS NULL` before either writes, so both "succeed" and the
        revocation chain above never fires. The lock forces the second caller to wait
        for the first's commit and then see the state that commit actually produced,
        which is what makes the two branches below mutually exclusive for the same
        row. It stays held until this method's own commit or the caller's -- there is
        no commit between the SELECT and the write in either branch, on purpose."""
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.jti == jti, RefreshToken.user_id == user_id)
            .with_for_update()
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        now = datetime.now(UTC)
        if record is None or record.expires_at < now:
            raise ValidationFailed("refresh_token", "jti", INVALID_REFRESH_TOKEN)
        if record.consumed_at is not None:
            self._revoke_all_valid(user_id, now)
            raise ValidationFailed("refresh_token", "jti", INVALID_REFRESH_TOKEN)
        record.consumed_at = now
        self.session.commit()

    def _revoke_all_valid(self, user_id: UUID, now: datetime) -> None:
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.consumed_at.is_(None),
            RefreshToken.expires_at >= now,
        )
        for record in self.session.execute(stmt).scalars():
            record.consumed_at = now
        self.session.commit()
