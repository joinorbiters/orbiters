"""deals.chiuso_il, documents.stato_dal with its backfill, and automation_config

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-02

Numbered 0023 and not 0008: the brief for this task says 0008/0007, but the head of
`migrations/versions` is 0022 (`0022_sort_indexes.py`), and a revision that claims an
occupied number is a branch, not a migration.

Three objects in one revision because they are meaningless apart: the automation cannot
run without its config row and cannot record a closure without the column. The
`automation_config` section is written by Task B3; this file applies cleanly with or
without it.

**The backfill is asymmetric, and the asymmetry is the whole argument of spec §4.1.**

`documents.stato_dal` is backfilled from `activities`: the offer timeline's payload is
`{"da": "inviata", "a": "accettata"}` -- literals of `OfferState`, not text a user can
edit -- so `occurred_at` of the most recent `state_changed` for a document is a reliable
answer. Projected to a date in the emitter's zone, not in UTC, for the reason
`db/clock.py` exists.

`deals.chiuso_il` is **not** backfilled. `DealService.move_stage` records the stage
*names* in its payload -- `{"from": <nome>, "to": <nome>}` -- and a user is free to rename
a stage (residuo R15), so deducing a historical closure would mean matching a mutable
string, which is precisely what `pipeline_stages.code` and `tipo` exist to avoid. Rows
closed before this migration keep `chiuso_il IS NULL`, the period dashboards exclude them
and declare how many they excluded. A guessed conversion rate is the worst kind of figure:
plausible and wrong.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must equal `Settings.timezone`'s default. Hardcoded here rather than read from settings
# because a migration must be reproducible: re-running it on a differently configured
# deployment has to produce the same rows it produced the first time.
_BACKFILL_TZ = "Europe/Rome"


def upgrade() -> None:
    op.add_column("deals", sa.Column("chiuso_il", sa.Date(), nullable=True))
    op.create_index("ix_deals_chiuso_il", "deals", ["chiuso_il"])

    op.add_column("documents", sa.Column("stato_dal", sa.Date(), nullable=True))
    op.create_index("ix_documents_stato_dal", "documents", ["stato_dal"])

    # One statement, not a loop: `DISTINCT ON` gives the latest state change per document
    # directly, and a Python loop over a million-row activities table inside a migration
    # is how a deploy times out.
    op.execute(
        sa.text(
            """
            UPDATE documents AS d
               SET stato_dal = latest.giorno
              FROM (
                    SELECT DISTINCT ON (a.entity_id)
                           a.entity_id,
                           (a.occurred_at AT TIME ZONE :tz)::date AS giorno
                      FROM activities AS a
                     WHERE a.entity_type = 'document'
                       AND a.kind = 'state_changed'
                     ORDER BY a.entity_id, a.occurred_at DESC, a.id DESC
                   ) AS latest
             WHERE d.id = latest.entity_id
               AND d.stato IS NOT NULL
            """
        ).bindparams(tz=_BACKFILL_TZ)
    )

    # `deals.chiuso_il` is deliberately NOT backfilled. See the module docstring.

    # -- automation_config: written by Task B3, in this same revision. --


def downgrade() -> None:
    op.drop_index("ix_documents_stato_dal", table_name="documents")
    op.drop_column("documents", "stato_dal")
    op.drop_index("ix_deals_chiuso_il", table_name="deals")
    op.drop_column("deals", "chiuso_il")
