"""comments: an append-only thread on a freelancer or a company

Revision ID: 0004
Revises: 0003

A new table, so nothing here is conditional. `entity_type` and `entity_id` name the row
the comment is about; the service refuses a row that does not exist, and the index is
the one query the hub makes: one thread, newest first.
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
        "comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("testo", sa.Text(), nullable=False),
        sa.Column("autore", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_comments_entity", "comments", ["entity_type", "entity_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_comments_entity", table_name="comments")
    op.drop_table("comments")
