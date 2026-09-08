"""invoices, invoice lines and the per-year counter

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMPS = (
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
)


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("stato", sa.String(length=12), nullable=False),
        sa.Column("anno", sa.Integer(), nullable=True),
        sa.Column("numero", sa.Integer(), nullable=True),
        sa.Column("riferimento", sa.String(length=30), nullable=True),
        sa.Column("data_emissione", sa.Date(), nullable=True),
        sa.Column("data_scadenza", sa.Date(), nullable=True),
        sa.Column("tipo_documento", sa.String(length=4), nullable=False),
        sa.Column("divisa", sa.String(length=3), nullable=False),
        sa.Column("imponibile", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("imposta", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("bollo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("totale", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("causale", sa.String(length=200), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("snapshot_versione", sa.Integer(), nullable=True),
        sa.Column("stato_pagamento", sa.String(length=14), nullable=False),
        sa.Column("data_incasso", sa.Date(), nullable=True),
        sa.Column("trasmessa_esternamente_il", sa.Date(), nullable=True),
        sa.Column("xml_hash_sha256", sa.String(length=64), nullable=True),
        sa.Column("pdf_document_id", sa.Uuid(), nullable=True),
        sa.Column("xml_document_id", sa.Uuid(), nullable=True),
        sa.Column("origine_proforma_id", sa.Uuid(), nullable=True),
        sa.Column("annullata_il", sa.Date(), nullable=True),
        sa.Column("motivo_annullamento", sa.String(length=500), nullable=True),
        sa.Column("note_interne", sa.Text(), nullable=True),
        sa.Column("custom_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_TIMESTAMPS,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["pdf_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["xml_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["origine_proforma_id"], ["invoices.id"]),
        sa.CheckConstraint(
            "(tipo = 'fattura' AND stato IN ('bozza', 'emessa', 'annullata')) "
            "OR (tipo = 'proforma' AND stato IN ('bozza', 'confermata', 'consumata'))",
            name="ck_invoices_tipo_stato",
        ),
        sa.CheckConstraint(
            "(anno IS NULL) = (numero IS NULL)", name="ck_invoices_anno_numero_together"
        ),
        sa.CheckConstraint(
            "numero IS NULL OR (tipo = 'fattura' AND stato <> 'bozza')",
            name="ck_invoices_numero_requires_issued_fattura",
        ),
        sa.CheckConstraint("numero IS NULL OR numero > 0", name="ck_invoices_numero_positive"),
        sa.CheckConstraint(
            "riferimento IS NULL OR tipo = 'proforma'",
            name="ck_invoices_riferimento_only_on_proforma",
        ),
        sa.CheckConstraint(
            "(snapshot IS NULL) = (snapshot_versione IS NULL)",
            name="ck_invoices_snapshot_together",
        ),
        sa.CheckConstraint(
            "(annullata_il IS NULL AND motivo_annullamento IS NULL) "
            "OR (stato = 'annullata' AND annullata_il IS NOT NULL "
            "AND motivo_annullamento IS NOT NULL)",
            name="ck_invoices_annullamento_complete",
        ),
        sa.CheckConstraint(
            "data_incasso IS NULL OR stato_pagamento = 'incassato'",
            name="ck_invoices_incasso_requires_state",
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (numero IS NULL AND stato <> 'consumata')",
            name="ck_invoices_no_delete_once_consumed",
        ),
    )
    op.create_index("ix_invoices_customer_id", "invoices", ["customer_id"])
    op.create_index("ix_invoices_deal_id", "invoices", ["deal_id"])
    # Autogenerate is known to drop both of these shapes -- a partial unique index and
    # a GIN index -- so they are written by hand and named in
    # test_migrations.HAND_MAINTAINED_INDEXES.
    op.create_index(
        "uq_invoices_anno_numero",
        "invoices",
        ["anno", "numero"],
        unique=True,
        postgresql_where=sa.text("numero IS NOT NULL"),
    )
    op.create_index(
        "ix_invoices_custom_fields", "invoices", ["custom_fields"], postgresql_using="gin"
    )

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("numero_linea", sa.Integer(), nullable=False),
        sa.Column("descrizione", sa.String(length=1000), nullable=False),
        sa.Column("quantita", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("unita_misura", sa.String(length=10), nullable=True),
        sa.Column("prezzo_unitario", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("sconto_percentuale", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("sconto_importo", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("prezzo_totale", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("aliquota_iva", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("natura", sa.String(length=4), nullable=True),
        sa.Column("riferimento_normativo", sa.Text(), nullable=True),
        *_TIMESTAMPS,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.UniqueConstraint("invoice_id", "numero_linea", name="uq_invoice_lines_invoice_numero"),
        sa.CheckConstraint(
            "(aliquota_iva = 0) = (natura IS NOT NULL)",
            name="ck_invoice_lines_natura_agrees_with_rate",
        ),
        sa.CheckConstraint("numero_linea >= 1", name="ck_invoice_lines_numero_positive"),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])

    op.create_table(
        "invoice_counters",
        sa.Column("anno", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ultimo_numero", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("anno"),
        sa.CheckConstraint("ultimo_numero >= 0", name="ck_invoice_counters_non_negative"),
    )

    # The right tool *here* and the wrong one for the fiscal number, for the same
    # property: `nextval()` does not roll back. A gap in a proforma reference means
    # nothing, and in exchange the counter serialises nobody.
    op.execute("CREATE SEQUENCE proforma_riferimento_seq AS bigint START WITH 1 INCREMENT BY 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE proforma_riferimento_seq")
    op.drop_table("invoice_counters")
    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_custom_fields", table_name="invoices")
    op.drop_index("uq_invoices_anno_numero", table_name="invoices")
    op.drop_index("ix_invoices_deal_id", table_name="invoices")
    op.drop_index("ix_invoices_customer_id", table_name="invoices")
    op.drop_table("invoices")
