"""space_settings

Revision ID: 0028
Revises: 0027

One key/value table, for the settings a space decides for itself (spec 2026-09-08: a
space has no operator and no process of its own, so what would be an environment
variable lives in its database). The root may use it too; a row wins over the
environment for the keys `space_settings/schemas.py` lists. Values are text, as an
environment variable is; the code gives them back their type when it reads them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "space_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("space_settings")
