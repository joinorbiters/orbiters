"""gmail messages and their links

Revision ID: 0015
Revises: 0014

The two tables the sync writes: one row per synchronised message, and the many-to-many
that files a message against the CRM entities it concerns.

`uq_gmail_messages_account_message` is the load-bearing constraint of the whole cycle.
The watermark is deliberately rolled back by 24 hours on every run so that a message
arriving across the boundary of two cycles is not lost, which means every cycle re-reads
a day of already-stored messages; the constraint is what makes that free. It is also the
only thing that holds when two syncs overlap in time -- a `SELECT` before the `INSERT`
is a check both of them pass, and only the database can arbitrate.

`gmail_message_links.entity_id` is deliberately not a foreign key: it addresses a
customer, a person or a deal depending on `entity_type`, and no single FK can express
that. Its own unique constraint is on the triple, so the same message cannot be filed
twice against the same entity however many times a cycle re-reads it.

Both foreign keys cascade. Disconnecting a mailbox and deleting its correspondence must
not leave orphaned rows holding somebody's private mail behind an account that no longer
exists.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gmail_messages",
        sa.Column("google_account_id", sa.Uuid(), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=128), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=128), nullable=False),
        sa.Column("message_id_header", sa.String(length=998), nullable=False),
        sa.Column("in_reply_to", sa.String(length=998), nullable=False),
        sa.Column("references", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("to_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cc_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("snippet", sa.String(length=500), nullable=False),
        sa.Column("internal_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_truncated", sa.Boolean(), nullable=False),
        sa.Column("body_html_scartato", sa.Boolean(), nullable=False),
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["google_account_id"], ["google_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "google_account_id", "gmail_message_id", name="uq_gmail_messages_account_message"
        ),
    )
    op.create_index(
        "ix_gmail_messages_thread_date",
        "gmail_messages",
        ["gmail_thread_id", "internal_date"],
        unique=False,
    )
    op.create_table(
        "gmail_message_links",
        sa.Column("gmail_message_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["gmail_message_id"], ["gmail_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gmail_message_id", "entity_type", "entity_id", name="uq_gmail_message_links_triple"
        ),
    )
    op.create_index(
        "ix_gmail_message_links_entity",
        "gmail_message_links",
        ["entity_type", "entity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_gmail_message_links_entity", table_name="gmail_message_links")
    op.drop_table("gmail_message_links")
    op.drop_index("ix_gmail_messages_thread_date", table_name="gmail_messages")
    op.drop_table("gmail_messages")
