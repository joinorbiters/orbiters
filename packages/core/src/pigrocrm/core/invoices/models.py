"""The three tables, and the constraints that carry the invariants.

Spec 14.4 asks for immutability "imposed by the database, not by the service", and
that is the organising idea of this file: the legal `(tipo, stato)` pairs, the
agreement between a zero rate and a `Natura`, the impossibility of a numbered row
carrying a `deleted_at`, and the uniqueness of `(anno, numero)` are all table
constraints. An invariant only the service defends is an invariant an importer, a
fix-up script or a psql session walks straight past -- and on a fiscal register that is
not a hypothetical.

`String(n)` + a Pydantic `Literal`, never a Postgres `ENUM`: that is how every closed
set in this schema is already spelled (`pipeline_stages.tipo` is `String(10)`,
`documents.tipo` is `String(20)`), and it means a future value costs a schema constant
rather than an `ALTER TYPE` migration. The closed sets that must also hold across write
paths get a `CHECK` on top, which an `ENUM` would not have made unnecessary anyway --
an `ENUM` cannot express that `stato` depends on `tipo`.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin

PROFORMA_SEQUENCE_NAME = "proforma_riferimento_seq"

# Attached to the metadata, not only created by the migration. The test suite builds its
# schema with `Base.metadata.create_all` (packages/core/tests/conftest.py), so a sequence
# that exists only as raw SQL inside `0005_invoices.py` is absent under test and present
# in production -- which is the worst of the two, because the difference only shows up
# the first time something calls `nextval`. Declaring it here emits it on both paths.
PROFORMA_SEQUENCE = Sequence(PROFORMA_SEQUENCE_NAME, start=1, increment=1, metadata=Base.metadata)


class Invoice(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A fiscal invoice or a proforma. One table, because lists, timeline and search
    stay one query and `tipo` already carries the difference."""

    __tablename__ = "invoices"

    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    deal_id: Mapped[UUID | None] = mapped_column(ForeignKey("deals.id"), default=None, index=True)
    # `String(20)`, matching `documents.tipo`, not the 10 that would just fit the two
    # legal values. The point of this file is that the `CHECK` carries the invariant, and
    # at 10 a wrong `tipo` longer than that dies on the column width first: Postgres
    # answers `StringDataRightTruncation` instead of a named constraint violation, which
    # is the raw-exception-reaching-the-caller family this project has already closed six
    # times. Width to spare is what lets the constraint be the thing that refuses.
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    stato: Mapped[str] = mapped_column(String(12), nullable=False)
    # `NULL` until emission. That is what makes "a failed creation cannot burn a
    # number" true by construction rather than by care.
    anno: Mapped[int | None] = mapped_column(Integer, default=None)
    numero: Mapped[int | None] = mapped_column(Integer, default=None)
    riferimento: Mapped[str | None] = mapped_column(String(30), default=None)
    # `Date`, never a timestamp: this is the date printed on the document and the one
    # that decides the fiscal year, not an instant. Acme's `toISOString()` moved an
    # invoice issued on 31 December at 23:30 CET into the next year.
    data_emissione: Mapped[date | None] = mapped_column(Date, default=None)
    data_scadenza: Mapped[date | None] = mapped_column(Date, default=None)
    tipo_documento: Mapped[str] = mapped_column(String(4), nullable=False, default="TD01")
    divisa: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Derived by the service and stored. Never recomputed by a client: a total computed
    # in the browser is the structural defect this slice exists to remove.
    imponibile: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    imposta: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    bollo: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    totale: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    causale: Mapped[str | None] = mapped_column(String(200), default=None)
    # Both parties' identity and the fiscal parameters as they were at emission.
    # `NULL` on a draft and on a proforma.
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    # An integer because a snapshot written today is read by code from three years
    # hence, and an unversioned JSON payload is interpreted by guessing.
    snapshot_versione: Mapped[int | None] = mapped_column(Integer, default=None)
    stato_pagamento: Mapped[str] = mapped_column(String(14), nullable=False, default="da_incassare")
    data_incasso: Mapped[date | None] = mapped_column(Date, default=None)
    # Why this column exists even though the slice performs no transmission: the XML
    # is a deliverable the user hands to their own intermediary. Without it the system
    # could not tell an invoice that never left -- annullable -- from one already
    # deposited with the Agenzia delle Entrate, and would treat both the same.
    trasmessa_esternamente_il: Mapped[date | None] = mapped_column(Date, default=None)
    xml_hash_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    pdf_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), default=None)
    xml_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), default=None)
    # A conversion is a new row pointing at the proforma, not a state change in place:
    # otherwise "immutable after emission" would be a property of something that *was*
    # mutable, verifiable only by reconstructing the history.
    origine_proforma_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("invoices.id"), default=None
    )
    annullata_il: Mapped[date | None] = mapped_column(Date, default=None)
    motivo_annullamento: Mapped[str | None] = mapped_column(String(500), default=None)
    note_interne: Mapped[str | None] = mapped_column(Text, default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        # Two state machines share one column, so the legal pairs are a table
        # constraint and not a convention of the service: `stato = 'consumata'` on a
        # `fattura` is not storable at all.
        CheckConstraint(
            "(tipo = 'fattura' AND stato IN ('bozza', 'emessa', 'annullata')) "
            "OR (tipo = 'proforma' AND stato IN ('bozza', 'confermata', 'consumata'))",
            name="ck_invoices_tipo_stato",
        ),
        CheckConstraint(
            "(anno IS NULL) = (numero IS NULL)", name="ck_invoices_anno_numero_together"
        ),
        CheckConstraint(
            "numero IS NULL OR (tipo = 'fattura' AND stato <> 'bozza')",
            name="ck_invoices_numero_requires_issued_fattura",
        ),
        CheckConstraint("numero IS NULL OR numero > 0", name="ck_invoices_numero_positive"),
        CheckConstraint(
            "riferimento IS NULL OR tipo = 'proforma'",
            name="ck_invoices_riferimento_only_on_proforma",
        ),
        CheckConstraint(
            "(snapshot IS NULL) = (snapshot_versione IS NULL)",
            name="ck_invoices_snapshot_together",
        ),
        CheckConstraint(
            "(annullata_il IS NULL AND motivo_annullamento IS NULL) "
            "OR (stato = 'annullata' AND annullata_il IS NOT NULL "
            "AND motivo_annullamento IS NOT NULL)",
            name="ck_invoices_annullamento_complete",
        ),
        CheckConstraint(
            "data_incasso IS NULL OR stato_pagamento = 'incassato'",
            name="ck_invoices_incasso_requires_state",
        ),
        # Spec 4: what never consumed a number is deletable; what consumed one is not,
        # not even by direct SQL -- and neither is a `consumata` proforma, which is the
        # antecedent of an immutable document.
        CheckConstraint(
            "deleted_at IS NULL OR (numero IS NULL AND stato <> 'consumata')",
            name="ck_invoices_no_delete_once_consumed",
        ),
        # The net under the row lock, not the mechanism (spec 3): it turns any future
        # path that bypasses the lock -- a direct INSERT, an importer, a second service
        # -- into an error instead of a duplicate. Partial, because every unnumbered
        # draft would otherwise be a duplicate of every other.
        Index(
            "uq_invoices_anno_numero",
            "anno",
            "numero",
            unique=True,
            postgresql_where=text("numero IS NOT NULL"),
        ),
        Index("ix_invoices_custom_fields", "custom_fields", postgresql_using="gin"),
        # The tenth trigram index (spec 6 §8.3), and the one that lets the global palette
        # look at invoices at all: `causale` is the only free-text column on this table and
        # `SearchRepository.invoices` matches it with `ILIKE '%…%'`, which no B-tree can
        # serve. Declared here and not only in migration 0024 because
        # `Base.metadata.create_all` is what builds the test schema -- an index that exists
        # only in a migration is invisible to every plan assertion in the suite.
        #
        # Partial on `deleted_at IS NULL` like the other nine: it is the condition every
        # search carries, so the index is smaller and residuo R7 closes for this table too.
        # The other half of the branch -- a fiscal number matched by equality -- needs no
        # index of its own: `uq_invoices_anno_numero` above already serves it.
        Index(
            "ix_invoices_causale_trgm",
            "causale",
            postgresql_using="gin",
            postgresql_ops={"causale": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class InvoiceLine(Base, PrimaryKeyMixin, TimestampMixin):
    """One `DettaglioLinee`.

    Acme sent one line per invoice -- `NumeroLinea` hardcoded to 1, quantity 1, the
    whole total as the unit price -- so the detail of the work never reached the
    customer.

    `numero_linea` is unique per invoice, starts at 1, and is contiguous. The first two
    are database constraints; **contiguity is a service invariant**, maintained by
    `InvoiceService.replace_lines` renumbering the whole list from 1, because no
    single-row `CHECK` can see the other rows. Saying so plainly is better than
    implying the database guarantees more than it does.
    """

    __tablename__ = "invoice_lines"

    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    numero_linea: Mapped[int] = mapped_column(Integer, nullable=False)
    # String(1000), mirroring FPR12's own `String1000LatinType`, with the matching
    # Pydantic `max_length` in schemas.py. Not `Text`: a width the schema already
    # imposes is a width worth having on the column, so an over-long value is refused
    # before it reaches an SdI validator.
    descrizione: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Numeric(12, 6): a factor, not an amount. See the class docstring on Invoice.
    quantita: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    unita_misura: Mapped[str | None] = mapped_column(String(10), default=None)
    prezzo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    sconto_percentuale: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    sconto_importo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    prezzo_totale: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    aliquota_iva: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    natura: Mapped[str | None] = mapped_column(String(4), default=None)
    riferimento_normativo: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (
        UniqueConstraint("invoice_id", "numero_linea", name="uq_invoice_lines_invoice_numero"),
        # The two checks the SdI applies as a pair, as one table constraint: a zero
        # rate without a Natura is rejected, and a Natura with a non-zero rate is
        # rejected. The invalid combination is therefore not storable, so it is not
        # exportable either.
        CheckConstraint(
            "(aliquota_iva = 0) = (natura IS NOT NULL)",
            name="ck_invoice_lines_natura_agrees_with_rate",
        ),
        CheckConstraint("numero_linea >= 1", name="ck_invoice_lines_numero_positive"),
    )


class InvoiceCounter(Base):
    """One row per year, locked with `SELECT ... FOR UPDATE` inside the emission
    transaction (spec 3).

    **Not a `SEQUENCE`**, and the reason is the property a sequence proudly does not
    have: `nextval()` in Postgres is deliberately non-transactional and does not roll
    back, so every aborted transaction would leave a permanent gap -- which is exactly
    what "progressive numbering with no gaps" forbids. A sequence guarantees uniqueness
    and prohibits the one property that is actually required here.

    Keyed by `anno` rather than by a UUID: the year *is* the identity, and a surrogate
    key would need a uniqueness constraint on `anno` anyway. No `TimestampMixin`
    either -- this row is a lock target, not a record of anything.
    """

    __tablename__ = "invoice_counters"

    anno: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ultimo_numero: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("ultimo_numero >= 0", name="ck_invoice_counters_non_negative"),
    )


__all__ = ["PROFORMA_SEQUENCE_NAME", "Invoice", "InvoiceCounter", "InvoiceLine"]
