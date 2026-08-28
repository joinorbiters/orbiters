"""gmail known addresses

Revision ID: 0016
Revises: 0015

The register that makes "an address added to the CRM gets its history read" happen
without `PersonService` ever learning what Gmail is. Each cycle compares the roster
against this table and treats the difference as a backfill: the new address is searched
over `gmail_backfill_days`, the established ones only from the watermark.

Per account, and `uq_gmail_known_addresses` says so. Two users may both correspond with
the same client, and each mailbox has to be searched back over that address once on its
own -- a global register would give whichever mailbox synced second nothing at all.

The foreign key cascades, like every other one in this slice: disconnecting a mailbox
must not leave rows behind describing what it once went looking for.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gmail_known_addresses",
        sa.Column("google_account_id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.UniqueConstraint("google_account_id", "address", name="uq_gmail_known_addresses"),
    )


def downgrade() -> None:
    op.drop_table("gmail_known_addresses")
