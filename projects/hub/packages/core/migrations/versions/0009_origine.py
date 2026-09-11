"""origine: which page of the site a freelancer or a company started from

Revision ID: 0009
Revises: 0008

One nullable column on `freelancers` and one on `companies` (ORB-167): the slug of the
page the person clicked through from, `home` or `pigrocrm`, beside the campaign the
UTM columns already hold. Rows written before this stay NULL: nobody knows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("freelancers", sa.Column("origine", sa.String(length=40), nullable=True))
    op.add_column("companies", sa.Column("origine", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "origine")
    op.drop_column("freelancers", "origine")
