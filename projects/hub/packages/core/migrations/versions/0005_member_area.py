"""magic_link_tokens and member_sessions: a freelancer's way back into the hub

Revision ID: 0005
Revises: 0004

Two new tables, nothing conditional. Both hang on `freelancers.id` with ON DELETE
CASCADE: a deleted person takes their tokens and sessions with them. The shape is the
admin session's (0003) plus `used_at` on the token, which is what makes a link single
use (member area spec, 2026-09-10).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "freelancer_id",
            sa.Uuid(),
            sa.ForeignKey("freelancers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_magic_link_tokens_token_hash"),
    )
    op.create_index("ix_magic_link_tokens_freelancer_id", "magic_link_tokens", ["freelancer_id"])

    op.create_table(
        "member_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "freelancer_id",
            sa.Uuid(),
            sa.ForeignKey("freelancers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_member_sessions_token_hash"),
    )
    op.create_index("ix_member_sessions_freelancer_id", "member_sessions", ["freelancer_id"])


def downgrade() -> None:
    op.drop_index("ix_member_sessions_freelancer_id", table_name="member_sessions")
    op.drop_table("member_sessions")
    op.drop_index("ix_magic_link_tokens_freelancer_id", table_name="magic_link_tokens")
    op.drop_table("magic_link_tokens")
