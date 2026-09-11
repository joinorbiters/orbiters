"""guide_downloads: who fetched the guide, and when

Revision ID: 0006
Revises: 0005

One table, nothing conditional. A row per download of the guide by a member (ORB-156),
hanging on `freelancers.id` with ON DELETE CASCADE like the member's sessions do (0005).
The admin area reads it as a counter and a recent list; nothing else writes it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guide_downloads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "freelancer_id",
            sa.Uuid(),
            sa.ForeignKey("freelancers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "downloaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_guide_downloads_freelancer_id", "guide_downloads", ["freelancer_id"])


def downgrade() -> None:
    op.drop_index("ix_guide_downloads_freelancer_id", table_name="guide_downloads")
    op.drop_table("guide_downloads")
