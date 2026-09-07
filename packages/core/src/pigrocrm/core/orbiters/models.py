from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pigrocrm.core.db.base import PrimaryKeyMixin


class OrbitersBase(DeclarativeBase):
    """Its own metadata, on purpose: nothing here may ever join `Base.metadata`, or the
    CRM's Alembic autogenerate would start proposing this table for every installation."""


class Signup(OrbitersBase, PrimaryKeyMixin):
    __tablename__ = "signups"

    # Same width and the same case-insensitive uniqueness as `users.email`: the
    # service lowers the address before writing, and the functional index is what
    # makes that a database fact rather than an app-level habit.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("uq_orbiters_signups_email_lower", func.lower(email), unique=True),)
