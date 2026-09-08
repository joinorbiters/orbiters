"""ix_activities_recent, and the tenth trigram index

Revision ID: 0024
Revises: 0023

Objects this slice's dashboards need, in one revision because they exist for the same
reason: a query slice 6 introduces would otherwise be a sequential scan on a table that
grows with use.

`ix_activities_recent` serves the *global* activity feed of §6.1.
`ix_activities_entity` cannot: its ordering column is third, so it can only order rows
that have already been filtered down to one entity. DESC on both members so the feed's own
`ORDER BY occurred_at DESC, id DESC` is a forward scan, and `id` present so the tie-break
is served by the index rather than by an in-memory sort -- the same shape, and the same
reasoning, as 0022's `ix_people_cognome_desc_id`.

The `invoices.causale` trigram index -- the tenth and last of spec §8.3 -- is here for the
same reason: `SearchRepository.invoices` matches that column with `ILIKE '%…%'`, and
without the index the fifth search branch reads the whole fiscal register on every
keystroke. It was left to Task C12 rather than written with the other nine in 0021 because
until that task there was no invoice branch to serve.

Written as raw SQL rather than `op.create_index` for the reason 0022 records: a descending
expression index has no `op.create_index` spelling. `CONCURRENTLY` is not used because
Alembic runs each migration in a transaction and `CREATE INDEX CONCURRENTLY` cannot run in
one; every statement carries `IF NOT EXISTS` so an operator who built it out-of-band is not
blocked.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_activities_recent ON activities (occurred_at DESC, id DESC)"
    )
    # The tenth trigram index of spec §8.3, and the last one: it is what lets the palette
    # search `invoices.causale` with `ILIKE '%…%'` instead of sequentially scanning the
    # fiscal register on every keystroke. Partial on `deleted_at IS NULL`, matching the
    # other nine and the declaration in `invoices/models.py`.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_invoices_causale_trgm ON invoices "
        "USING gin (causale gin_trgm_ops) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_invoices_causale_trgm")
    op.execute("DROP INDEX IF EXISTS ix_activities_recent")
