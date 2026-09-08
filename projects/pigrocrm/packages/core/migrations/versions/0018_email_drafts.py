"""email drafts

Revision ID: 0018
Revises: 0017

The message being written, and the record of what happened to it. Written before Gmail
is called (spec 6.2), which is what keeps hand-typed text out of reach of an HTTP error
and what gives the reconciliation of spec 6.3 an id it can look the message up by.

Three things in this table are decisions rather than defaults:

* `uq_email_drafts_message_id`. The reconciliation finds a draft *by* its Message-ID, so
  two drafts sharing one would make that lookup ambiguous at the one moment it matters.
  uuid7 makes a collision vanishingly unlikely; the constraint makes it impossible, and
  the difference between those two is the whole reason the previous system's JSON file lost writes.
* `in_reply_to_message_id` is `ON DELETE SET NULL`, not `CASCADE`, unlike every other
  foreign key in this slice. A draft is the user's own text: the message it answers going
  away is no reason to delete it, it only stops being a reply.
* `payment_reminder_id` carries **no** foreign key, because `payment_reminders` does not
  exist until B2-8; that task adds the constraint in its own revision. Stated here so the
  absence is a decision on the record rather than something to rediscover.

`entity_id` also has no foreign key, for the same reason as `gmail_message_links`: it
points at a customer, a person or a deal depending on `entity_type`, and no single
constraint can express that. `EmailDraftService` validates it against the table
`entity_type` names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_drafts",
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("to_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cc_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column(
            "attachment_version_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("message_id_header", sa.String(length=998), nullable=False),
        sa.Column("in_reply_to_message_id", sa.Uuid(), nullable=True),
        sa.Column("send_state", sa.String(length=10), nullable=False),
        sa.Column("send_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("sent_gmail_message_id", sa.String(length=128), nullable=True),
        sa.Column("payment_reminder_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["in_reply_to_message_id"], ["gmail_messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id_header", name="uq_email_drafts_message_id"),
    )
    op.create_index("ix_email_drafts_entity", "email_drafts", ["entity_type", "entity_id"])
    op.create_index("ix_email_drafts_send_state", "email_drafts", ["send_state"])


def downgrade() -> None:
    op.drop_index("ix_email_drafts_send_state", table_name="email_drafts")
    op.drop_index("ix_email_drafts_entity", table_name="email_drafts")
    op.drop_table("email_drafts")
