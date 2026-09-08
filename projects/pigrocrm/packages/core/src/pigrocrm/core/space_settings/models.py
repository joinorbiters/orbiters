from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base


class SpaceSetting(Base):
    """One row per overridden key. Values are strings, the way an environment variable
    is; `apply_overrides` gives them back the type `Settings` declares."""

    __tablename__ = "space_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
