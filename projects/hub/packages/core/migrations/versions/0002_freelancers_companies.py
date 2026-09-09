"""freelancers and companies: what the hub's two wizards collect

Revision ID: 0002
Revises: 0001

Two tables, both new, so nothing here is conditional: 0001 was the adoption of an
inherited table, and from here on this history owns the schema. The CV is a `bytea` in
the row (hub spec, Ivan's decision): personal data with a retention to honour lives in
one place, and one place is one place to delete from.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utm_columns() -> list[sa.Column[str | None]]:
    return [
        sa.Column(name, sa.String(length=200), nullable=True)
        for name in (
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
            "utm_id",
        )
    ]


def upgrade() -> None:
    op.create_table(
        "freelancers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("cognome", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("linkedin_url", sa.String(length=300), nullable=True),
        sa.Column("cv_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("cv_filename", sa.String(length=255), nullable=False),
        sa.Column("cv_mime", sa.String(length=100), nullable=False),
        sa.Column("cv_size", sa.Integer(), nullable=False),
        sa.Column("tariffa_giornaliera", sa.Numeric(10, 2), nullable=False),
        sa.Column("posizione", sa.String(length=160), nullable=False),
        sa.Column("remoto", sa.String(length=10), nullable=False),
        sa.Column("links", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stato", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_utm_columns(),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "uq_freelancers_email_lower", "freelancers", [sa.text("lower(email)")], unique=True
    )
    op.create_index("ix_freelancers_created_at", "freelancers", ["created_at"])

    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("nome_azienda", sa.String(length=200), nullable=False),
        sa.Column("referente", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("progetto", sa.Text(), nullable=False),
        sa.Column("periodo_da", sa.Date(), nullable=False),
        sa.Column("durata", sa.String(length=120), nullable=False),
        sa.Column("budget_giornaliero", sa.Numeric(10, 2), nullable=False),
        sa.Column("stato", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_utm_columns(),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_companies_created_at", "companies", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_companies_created_at", table_name="companies")
    op.drop_table("companies")
    op.drop_index("ix_freelancers_created_at", table_name="freelancers")
    op.drop_index("uq_freelancers_email_lower", table_name="freelancers")
    op.drop_table("freelancers")
