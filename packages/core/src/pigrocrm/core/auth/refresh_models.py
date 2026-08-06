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
