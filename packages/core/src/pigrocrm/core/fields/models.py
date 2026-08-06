from typing import Any

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class FieldDefinition(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "field_definitions"
    __table_args__ = (UniqueConstraint("entity_type", "key", name="uq_field_entity_key"),)

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)
    options: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
