from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin


class Activity(Base, PrimaryKeyMixin):
    """One table for the whole timeline.

    Later slices append emails, documents, invoices and time entries by writing new
    `kind` values — no migration. That is what makes the unified timeline free.
    """

    __tablename__ = "activities"
    __table_args__ = (Index("ix_activities_entity", "entity_type", "entity_id", "occurred_at"),)

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(default=None)
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
