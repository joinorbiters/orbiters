"""a link by mail is a way in: nullable password, verified-at, magic_link_tokens

Revision ID: 0034
Revises: 0033

Spec 2026-09-12 §6.2. In PigroCRM one enters as in the community, with a link by mail;
the password stays as a second way for whoever has one and is never asked again.

`users.password_hash` becomes nullable: a person who created their space through the
wizard has no password at all, and `UserService.authenticate` refuses such a user with
the same sentence and cost as a wrong password. `users.email_verificata_il` records the
first time a link by mail was used; that entry also revokes every refresh token issued
before it, which is what makes the session opened at signup safe.

`magic_link_tokens` holds the SHA-256 of each link sent, its expiry and when it was
spent. The downgrade puts the NOT NULL back and fails if a row has no password: it would
have to invent one, and it does not.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)
    op.add_column(
        "users", sa.Column("email_verificata_il", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        op.f("ix_magic_link_tokens_token_hash"), "magic_link_tokens", ["token_hash"], unique=True
    )
    op.create_index(
        op.f("ix_magic_link_tokens_user_id"), "magic_link_tokens", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_magic_link_tokens_user_id"), table_name="magic_link_tokens")
    op.drop_index(op.f("ix_magic_link_tokens_token_hash"), table_name="magic_link_tokens")
    op.drop_table("magic_link_tokens")
    op.drop_column("users", "email_verificata_il")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
