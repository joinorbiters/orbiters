"""customers.email index for Gmail relevance resolution

Revision ID: 0013
Revises: 0012

`people.email` has carried an index since 0001; `customers.email` never did, because
nothing looked a customer up by address. Gmail relevance (`core/gmail/roster.py`) does
exactly that, on both tables, for every message it considers -- so the missing index is
one sequential scan per message over the widest table in the CRM.

The name is `ix_customers_email` because that is what SQLAlchemy's default naming
convention produces for `index=True` on that column, and
`test_migrations_produce_exactly_the_models_schema` compares migrations against the
models: any other name reads as a schema drift.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_customers_email", "customers", ["email"])


def downgrade() -> None:
    op.drop_index("ix_customers_email", table_name="customers")
