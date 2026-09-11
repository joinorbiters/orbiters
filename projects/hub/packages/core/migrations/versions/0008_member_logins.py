"""member_logins: who entered the hub, and when

Revision ID: 0008
Revises: 0007

One new table, the shape of `guide_downloads` (0006): a row per login through the magic
link, hanging on the freelancer with ON DELETE CASCADE. The session table cannot serve
here, since it forgets a session on logout and on expiry (ORB-158).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "member_logins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "freelancer_id",
            sa.Uuid(),
            sa.ForeignKey("freelancers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_member_logins_freelancer_id", "member_logins", ["freelancer_id"])


def downgrade() -> None:
    op.drop_index("ix_member_logins_freelancer_id", table_name="member_logins")
    op.drop_table("member_logins")
