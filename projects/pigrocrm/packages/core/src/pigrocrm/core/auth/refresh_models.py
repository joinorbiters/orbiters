from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class RefreshToken(Base, PrimaryKeyMixin, TimestampMixin):
    """One row per refresh token ever issued. This is what makes the JWT's `jti` claim
    mean something: a bare signed token has no server-side presence of its own, so
    without a row to mark consumed there is nothing to stop it being replayed for its
    entire lifetime -- rotation and logout both need this table to actually revoke
    anything."""

    __tablename__ = "refresh_tokens"

    jti: Mapped[UUID] = mapped_column(unique=True, index=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # The token this one was rotated into, written in the same transaction that marks
    # this row consumed. Without it, a *second* presentation of the same refresh token
    # is indistinguishable from a stolen one being replayed, and the only safe answer is
    # to revoke the whole family -- which is what two tabs waking up past the same
    # fifteen-minute access cookie used to do to their owner. With it,
    # `RefreshTokenService.rotate` can hand the second presentation the very pair the
    # first produced, for as long as `REFRESH_GRACE_SECONDS` allows.
    #
    # Deliberately a bare UUID and not a ForeignKey to `jti`: the successor row is
    # created in the same flush as this write, so an FK would only constrain an order
    # this code already guarantees, and it would put a second row's lock on the
    # replay path -- the one path that must not fail. Nothing reads this column
    # except `rotate`, which tolerates a jti with no row (it revokes, as before).
    successor_jti: Mapped[UUID | None] = mapped_column(default=None)
