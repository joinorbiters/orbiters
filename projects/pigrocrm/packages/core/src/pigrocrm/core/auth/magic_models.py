from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class MagicLinkToken(Base, PrimaryKeyMixin, TimestampMixin):
    """One row per link sent (spec 2026-09-12 §6.2). Only the SHA-256 of the raw token
    is stored, so a dump of this table opens nothing. Spent rows keep `used_at`, so a
    second click can be told from a link that never existed; `MagicLinkService.request`
    sweeps a user's spent and expired rows before writing a new one."""

    __tablename__ = "magic_link_tokens"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
