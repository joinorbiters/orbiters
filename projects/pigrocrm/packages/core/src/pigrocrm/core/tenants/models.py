from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pigrocrm.core.db.base import PrimaryKeyMixin


class TenantsBase(DeclarativeBase):
    """Its own metadata: this table lives in the registry database, never in a space."""


class Tenant(TenantsBase, PrimaryKeyMixin):
    __tablename__ = "tenants"

    # Unique at the database, which is what makes two simultaneous signups with the
    # same name a race with exactly one winner (`TenantService.provision`).
    slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    db_name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    owner_email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
