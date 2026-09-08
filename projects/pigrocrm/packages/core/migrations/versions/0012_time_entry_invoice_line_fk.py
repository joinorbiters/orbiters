"""time entries: the real foreign key from invoice_line_id to invoice_lines

Revision ID: 0012
Revises: 0011

Plan 4A created `invoice_line_id` as a bare `Uuid` because `invoice_lines` is a slice 3
table and 4A deliberately does not depend on slice 3. Both tables exist now, so the
column becomes a real constraint.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No backfill and no cleanup pass before the constraint: nothing has ever written
    # this column -- `bind_time_to_invoice` is 4B -- so every existing row holds NULL and
    # there is no dangling value for the FK to choke on.
    #
    # `ON DELETE SET NULL` is what lets slice 3's wholesale line replacement (slice 3
    # §11) unbind and rebind hours without leaving orphans, and without slice 4 having to
    # join the locked transaction of slice 3 §3.
    op.create_foreign_key(
        "fk_time_entries_invoice_line",
        "time_entries",
        "invoice_lines",
        ["invoice_line_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_time_entries_invoice_line", "time_entries", type_="foreignkey")
