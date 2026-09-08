"""fiscal profile

Revision ID: 0004
Revises: 0003

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fiscal_profile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("singleton", sa.Boolean(), nullable=False),
        sa.Column("codice_regime", sa.String(length=4), nullable=False),
        sa.Column("aliquota_iva_default", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("natura_default", sa.String(length=4), nullable=True),
        sa.Column("riferimento_normativo", sa.Text(), nullable=True),
        sa.Column("applica_bollo", sa.Boolean(), nullable=False),
        sa.Column("soglia_bollo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("importo_bollo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("condizioni_pagamento", sa.String(length=4), nullable=False),
        sa.Column("modalita_pagamento", sa.String(length=4), nullable=False),
        sa.Column("giorni_scadenza", sa.Integer(), nullable=False),
        sa.Column("iban", sa.String(length=34), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("singleton"),
    )


def downgrade() -> None:
    op.drop_table("fiscal_profile")
