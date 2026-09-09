"""invoices: the accrual period, and a date on every proforma

Revision ID: 0033
Revises: 0032

Two columns and a backfill, for ORB-61 and ORB-63.

`competenza_da` / `competenza_a` are the days the invoiced work belongs to, as opposed
to the day the document was issued. Until now that month lived only in the free text of
`causale` ("FDE, agosto 2026"), where neither the XML nor the P&L could read it. Header
level, nullable, and guarded by the same two CHECKs the model declares: both ends or
neither, and in order. Existing rows stay `NULL`: nothing here can tell what period an
old invoice was for, and inventing one would put a fact on a frozen fiscal document
that nobody stated.

`data_emissione` on a proforma is the backfill. A proforma used to keep the column
`NULL` until a fattura was issued from it, and its PDF printed the day it was rendered
-- so the same document re-rendered a week later carried a different date. From this
revision a proforma is dated at creation and the PDF prints that date. The rows that
already exist get the civil date, in Europe/Rome, of their `created_at`: that is
exactly what `_for_export_proforma` used to print for them, so no PDF anyone has already
received changes its date. Scoped by `tipo`, so no fattura row is touched -- a `NULL`
`data_emissione` on a fattura means "draft, not yet issued" and must stay that way.

The downgrade drops the two columns and leaves the proforma dates in place: they are
true, code that predates this revision ignored the column on a proforma, and putting
`NULL` back would only make the PDF drift with the clock again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("competenza_da", sa.Date(), nullable=True))
    op.add_column("invoices", sa.Column("competenza_a", sa.Date(), nullable=True))
    op.create_check_constraint(
        "ck_invoices_competenza_together",
        "invoices",
        "(competenza_da IS NULL) = (competenza_a IS NULL)",
    )
    op.create_check_constraint(
        "ck_invoices_competenza_ordered",
        "invoices",
        "competenza_da IS NULL OR competenza_da <= competenza_a",
    )
    op.execute(
        """
        UPDATE invoices
           SET data_emissione = (created_at AT TIME ZONE 'Europe/Rome')::date
         WHERE tipo = 'proforma'
           AND data_emissione IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoices_competenza_ordered", "invoices", type_="check")
    op.drop_constraint("ck_invoices_competenza_together", "invoices", type_="check")
    op.drop_column("invoices", "competenza_a")
    op.drop_column("invoices", "competenza_da")
