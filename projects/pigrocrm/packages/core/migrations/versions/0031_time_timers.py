"""time_timers: the one clock a person may have running

Revision ID: 0031
Revises: 0030

One row per user, unique on `user_id`: a running timer is what somebody is doing right
now, and a person is doing one thing. Stopping it creates a `time_entries` row through
the ordinary path and deletes this one, so the table never grows past the number of
people with a clock running; discarding deletes it and writes nothing. No soft delete
for that reason -- the history is the entry, never the timer.

`deal_id` is nullable here and not on `time_entries`: a timer may start before the deal
is chosen, and the service makes the deal mandatory at the moment the timer becomes an
entry. Both foreign keys are plain (no cascade): a user or a deal is never hard-deleted
in this product.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "time_timers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("deal_id", sa.Uuid(), sa.ForeignKey("deals.id"), nullable=True),
        sa.Column("descrizione", sa.Text(), nullable=False),
        sa.Column("fatturabile", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ux_time_timers_user", "time_timers", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_time_timers_user", table_name="time_timers")
    op.drop_table("time_timers")
