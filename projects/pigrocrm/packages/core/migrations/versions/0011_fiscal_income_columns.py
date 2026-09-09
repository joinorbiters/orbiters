"""fiscal profile: the three income-calculation columns

Revision ID: 0011
Revises: 0010

Numbered 0011 and not 0005: 0005 is slice 3's, 0006-0009 are reserved by slice 6's own
plan, and 0010 is the head this branch starts from.
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The previous system's own profile, the values the forfettario uses, as percentages: `67.00` and
# not `0.67`. See `fiscal/schemas.py`, which carries the same three as schema defaults.
DEFAULTS = (
    ("coefficiente_redditivita", "67.00"),
    ("aliquota_imposta_sostitutiva", "5.00"),
    ("aliquota_inps", "26.07"),
)


def upgrade() -> None:
    for column, default in DEFAULTS:
        op.add_column(
            "fiscal_profile",
            sa.Column(column, sa.Numeric(precision=5, scale=2), nullable=True),
        )
        # Backfilled on the existing row too, not only defaulted for new ones: there is
        # exactly one row and it already exists, so a NULL here would leave the fiscal
        # estimate with nothing to compute from until somebody happened to open the
        # settings screen and press Salva.
        #
        # The bind carries an explicit `Numeric` type: passing the value as a bare
        # string makes psycopg cast it to VARCHAR, and Postgres refuses `numeric =
        # varchar` outright rather than coercing it.
        op.execute(
            sa.text(f"UPDATE fiscal_profile SET {column} = :value").bindparams(
                sa.bindparam("value", Decimal(default), type_=sa.Numeric(precision=5, scale=2))
            )
        )


def downgrade() -> None:
    for column, _ in reversed(DEFAULTS):
        op.drop_column("fiscal_profile", column)
