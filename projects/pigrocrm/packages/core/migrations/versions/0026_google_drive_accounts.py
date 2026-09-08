"""google_drive_accounts, and the oauth state's purpose

Revision ID: 0026
Revises: 0025

Spec 9 §5.2's second credential. `google_drive_accounts` is `google_accounts`'
twin and not a widening of it: a Drive connection and a Gmail connection are two
independent OAuth grants a person can hold, revoke and reconnect one at a time, so they
get two tables rather than one table doing double duty on a discriminator. See
`drive/models.py::GoogleDriveAccount` for the column-by-column reasoning.

`status` gets the `CheckConstraint` `google_accounts` never had, because this is a new
table and the four values are already the whole of what it is allowed to hold -- there
is no earlier revision here to interact badly with.

`google_oauth_states.purpose` is the second half: one in-flight authorisation registry
now serves both flows, and `purpose` is what a `/callback` for one cannot mistake for the
other. `server_default='gmail'` and not just an ORM-side default: it is what keeps every
row this table already held valid without a data migration, since every one of them
started a Gmail connection and none of them ever set the column that did not exist yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_drive_accounts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=False),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("scopes_granted", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("consent_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("root_folder_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("storage_folder_id", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'expired', 'disconnected')",
            name="ck_google_drive_accounts_status",
        ),
    )

    op.add_column(
        "google_oauth_states",
        sa.Column("purpose", sa.String(length=10), nullable=False, server_default="gmail"),
    )


def downgrade() -> None:
    op.drop_column("google_oauth_states", "purpose")
    op.drop_table("google_drive_accounts")
