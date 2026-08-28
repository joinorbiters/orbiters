from typing import Any

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin


class Customer(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """The first full business entity. `People` and `Deals` copy this file's shape.

    Fiscal fields (`partita_iva`, `codice_fiscale`, `codice_sdi`, `pec`) are first-class
    columns rather than custom fields, so slice 3 can build FatturaPA invoicing directly
    on them. `custom_fields` carries everything else a tenant defines through
    `FieldDefinitionService`; the GIN index below is what keeps `list()`'s JSONB
    containment filter (`custom_fields @> {...}`) from ever needing a full table scan.
    """

    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_custom_fields", "custom_fields", postgresql_using="gin"),
        Index("ix_customers_ragione_sociale", "ragione_sociale"),
    )

    ragione_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    partita_iva: Mapped[str | None] = mapped_column(String(11), default=None, index=True)
    codice_fiscale: Mapped[str | None] = mapped_column(String(16), default=None)
    codice_sdi: Mapped[str | None] = mapped_column(String(7), default=None)
    pec: Mapped[str | None] = mapped_column(String(320), default=None)
    indirizzo: Mapped[str | None] = mapped_column(String(255), default=None)
    cap: Mapped[str | None] = mapped_column(String(10), default=None)
    comune: Mapped[str | None] = mapped_column(String(120), default=None)
    provincia: Mapped[str | None] = mapped_column(String(2), default=None)
    nazione: Mapped[str] = mapped_column(String(2), nullable=False, default="IT")
    # Indexed for the same reason people.email is: Gmail relevance resolution
    # (gmail/roster.py) looks an address up in both tables on every message it
    # considers, and an unindexed lookup there is a sequential scan per message.
    email: Mapped[str | None] = mapped_column(String(320), default=None, index=True)
    telefono: Mapped[str | None] = mapped_column(String(40), default=None)
    sito_web: Mapped[str | None] = mapped_column(String(255), default=None)
    stato: Mapped[str | None] = mapped_column(String(40), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
