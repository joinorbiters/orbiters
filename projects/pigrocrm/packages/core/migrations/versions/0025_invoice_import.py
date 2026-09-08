"""invoices.importata_da and invoice_register_gaps

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-04

Slice 9 §3. One column and one table, in one revision because neither means anything
without the other: an imported invoice exists to fill a register whose gaps are
declared in the second.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("importata_da", sa.String(length=20), nullable=True))
    op.create_table(
        "invoice_register_gaps",
        sa.Column("anno", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.String(length=500), nullable=False),
        sa.Column("dichiarato_da", sa.Uuid(), nullable=True),
        sa.Column("dichiarato_il", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["dichiarato_da"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("anno", "numero", name="uq_invoice_register_gaps_anno_numero"),
        sa.CheckConstraint("numero >= 1", name="ck_invoice_register_gaps_numero_positive"),
    )


def downgrade() -> None:
    op.drop_table("invoice_register_gaps")
    op.drop_column("invoices", "importata_da")
