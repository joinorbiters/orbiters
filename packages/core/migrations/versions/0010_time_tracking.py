"""time tracking: hours, costs, cost categories, period locks and the rate columns

Revision ID: 0010
Revises: 0005

Numbered 0010, not 0006: slice 3 took 0005, and slice 6's own plan already reserves
0006-0009 for itself. Taking the next free number after 0005 would collide with
work that plan describes but has not yet been written, so this slice starts at
0010 instead.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cost_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("nome", sa.String(length=60), nullable=False),
        sa.Column("posizione", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=True),
        sa.Column("archiviata", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_cost_categories_code", "cost_categories", ["code"], unique=True)
    # Matches `uq_users_email_lower`'s own idiom (0001): a functional index over
    # lower(nome), not a plain unique=True, which would be case-sensitive.
    op.create_index(
        "uq_cost_categories_nome",
        "cost_categories",
        [sa.literal_column("lower(nome)")],
        unique=True,
    )

    op.create_table(
        "time_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("ore", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("descrizione", sa.Text(), nullable=False),
        sa.Column("fatturabile", sa.Boolean(), nullable=False),
        sa.Column("tariffa_applicata", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("costo_applicato", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("tariffa_origine", sa.String(length=10), nullable=False),
        sa.Column("costo_origine", sa.String(length=10), nullable=False),
        # No ForeignKeyConstraint: `invoice_lines` is a slice 3 table and 4A does not
        # depend on slice 3. Task 4B-3's migration adds the constraint with
        # ON DELETE SET NULL once the relationship is wired.
        sa.Column("invoice_line_id", sa.Uuid(), nullable=True),
        sa.Column("note_interne", sa.Text(), nullable=True),
        sa.Column("custom_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("ore > 0 AND ore <= 24", name="ck_time_entries_ore_range"),
        sa.CheckConstraint(
            "deleted_at IS NULL OR invoice_line_id IS NULL",
            name="ck_time_entries_billed_not_deleted",
        ),
        sa.CheckConstraint(
            "tariffa_origine IN ('manuale', 'deal', 'utente', 'assente')",
            name="ck_time_entries_tariffa_origine",
        ),
        sa.CheckConstraint(
            "costo_origine IN ('manuale', 'utente', 'assente')",
            name="ck_time_entries_costo_origine",
        ),
    )
    op.create_index("ix_time_entries_deal_id", "time_entries", ["deal_id"])
    op.create_index("ix_time_entries_invoice_line_id", "time_entries", ["invoice_line_id"])
    op.create_index(
        "ix_time_entries_deal_data",
        "time_entries",
        ["deal_id", "data"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_time_entries_user_data",
        "time_entries",
        ["user_id", "data"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_time_entries_custom_fields", "time_entries", ["custom_fields"], postgresql_using="gin"
    )

    op.create_table(
        "costs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("importo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("descrizione", sa.Text(), nullable=False),
        sa.Column("fornitore", sa.String(length=200), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("custom_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["cost_categories.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("importo <> 0", name="ck_costs_importo_non_zero"),
    )
    op.create_index("ix_costs_deal_id", "costs", ["deal_id"])
    op.create_index("ix_costs_category_id", "costs", ["category_id"])
    op.create_index(
        "ix_costs_deal_data",
        "costs",
        ["deal_id", "data"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_costs_data", "costs", ["data"], postgresql_where=sa.text("deleted_at IS NULL")
    )
    op.create_index("ix_costs_custom_fields", "costs", ["custom_fields"], postgresql_using="gin")

    op.create_table(
        "period_locks",
        sa.Column("anno", sa.Integer(), nullable=False),
        sa.Column("mese", sa.Integer(), nullable=False),
        sa.Column("chiuso_il", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chiuso_da", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["chiuso_da"], ["users.id"]),
        sa.PrimaryKeyConstraint("anno", "mese"),
        sa.CheckConstraint("mese >= 1 AND mese <= 12", name="ck_period_locks_mese"),
    )

    op.add_column(
        "deals", sa.Column("tariffa_oraria", sa.Numeric(precision=12, scale=6), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("tariffa_oraria_default", sa.Numeric(precision=12, scale=6), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("costo_orario_default", sa.Numeric(precision=12, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "costo_orario_default")
    op.drop_column("users", "tariffa_oraria_default")
    op.drop_column("deals", "tariffa_oraria")
    op.drop_table("period_locks")
    op.drop_table("costs")
    op.drop_table("time_entries")
    op.drop_table("cost_categories")
