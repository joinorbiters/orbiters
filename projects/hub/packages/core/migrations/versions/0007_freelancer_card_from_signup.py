"""freelancers: a card may be born from a signup, without a CV, a rate, a position or
a remote option, and says who filled it

Revision ID: 0007
Revises: 0006

An admin can now write a freelancer card from what the public web says about a signup
(ORB-155, spec 2026-09-11). Nothing public states a CV, a daily rate or where somebody
wants to work, so the seven columns the wizard fills become nullable and the person
completes them from the member area. `compilata_da` records who wrote the answers last:
`persona` (the wizard, the member area) or `admin` (research). It is added with a server
default so the rows already there read `persona`, which is true of them, and the default
is dropped right after: the model owns the default, as it does for `stato`.

The downgrade puts the NOT NULLs back and fails on a table holding an incomplete card,
on purpose: a downgrade that invents a CV is worse than one that stops.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOOSENED = (
    "cv_bytes",
    "cv_filename",
    "cv_mime",
    "cv_size",
    "tariffa_giornaliera",
    "posizione",
    "remoto",
)


def upgrade() -> None:
    for column in LOOSENED:
        op.alter_column("freelancers", column, nullable=True)
    op.add_column(
        "freelancers",
        sa.Column("compilata_da", sa.String(length=10), nullable=False, server_default="persona"),
    )
    op.alter_column("freelancers", "compilata_da", server_default=None)


def downgrade() -> None:
    op.drop_column("freelancers", "compilata_da")
    for column in reversed(LOOSENED):
        op.alter_column("freelancers", column, nullable=False)
