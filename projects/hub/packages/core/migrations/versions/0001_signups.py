"""signups: the table this product inherits, adopted as it stands

Revision ID: 0001
Revises:

The first migration of a database that already exists. PigroCRM's sidecar created
`signups` in production with `create_all` on 2026-09-07 and grew it by `ADD COLUMN IF
NOT EXISTS` twice; the rows in it are real people who asked to join. So every statement
here is conditional: a fresh database gets the whole table, the production database
gets nothing changed and an `alembic_version` row saying it is at 0001. The columns are
spelled exactly as SQLAlchemy created them, so `compare_metadata` reports no drift.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LATE_COLUMNS = (
    ("utm_source", 200),
    ("utm_medium", 200),
    ("utm_campaign", 200),
    ("utm_content", 200),
    ("utm_term", 200),
    ("utm_id", 200),
    ("nome", 120),
    ("cognome", 120),
    ("linkedin_url", 300),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS signups (
            id UUID NOT NULL,
            email VARCHAR(320) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id)
        )
        """
    )
    for column, width in _LATE_COLUMNS:
        op.execute(f"ALTER TABLE signups ADD COLUMN IF NOT EXISTS {column} VARCHAR({width})")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_orbiters_signups_email_lower "
        "ON signups (lower(email))"
    )


def downgrade() -> None:
    # Never drops the rows: a downgrade of the first revision on the production
    # database would delete the list. The index is the only thing undone.
    op.execute("DROP INDEX IF EXISTS uq_orbiters_signups_email_lower")
