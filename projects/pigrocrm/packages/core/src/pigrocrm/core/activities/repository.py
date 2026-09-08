from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity


class ActivityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, activity: Activity) -> Activity:
        self.session.add(activity)
        self.session.flush()
        return activity

    def timeline(self, entity_type: str, entity_id: UUID, limit: int) -> list[Activity]:
        stmt = (
            select(Activity)
            .where(Activity.entity_type == entity_type, Activity.entity_id == entity_id)
            .order_by(Activity.occurred_at.desc(), Activity.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def recent(self, limit: int = 50) -> list[Activity]:
        """The global activity feed of §6.1: newest first, across every entity.

        Not paginated, and fifty rows at most. A complete history of activity is the
        entity's own `timeline`, which already exists; a paginated global feed would be a
        second way to browse the same rows, with its own cursor to get wrong.

        Served by `ix_activities_recent`, and `test_search_plan.py` asserts on the plan --
        this query is fast either way on a small table and slow in production, which is the
        combination a latency test cannot catch. `ix_activities_entity` cannot serve it:
        its ordering column is third.

        The `id` tie-break is the same one `timeline` and `by_kind` carry, for the same
        reason: `occurred_at` has microsecond resolution and rows written in one
        transaction can share it.
        """
        return list(
            self.session.execute(
                select(Activity)
                .order_by(Activity.occurred_at.desc(), Activity.id.desc())
                .limit(limit)
            ).scalars()
        )

    def by_kind(self, kinds: Sequence[str], limit: int = 20) -> list[Activity]:
        """Activities of the given kinds, newest first, across every entity.

        Spec §9.5 and §11.1: the automation run log is a read of `activities` by `kind`,
        not a new table (§9.4). A dedicated execution log would be a table whose only
        function is answering a question `activities` answers better -- the same reasoning
        that made slice 3 refuse to historicise `fiscal_profile`.

        An empty `kinds` returns nothing. `IN ()` is not portable and a carelessly written
        empty filter matches everything, which here would dump the whole timeline into a
        settings page.

        The `id` tie-break mirrors `timeline` above: `occurred_at` has microsecond
        resolution and two automations firing inside one trigger's transaction can share
        it, at which point an unordered tie is a list that changes order between two reads
        of the same rows.
        """
        if not kinds:
            return []
        return list(
            self.session.execute(
                select(Activity)
                .where(Activity.kind.in_(list(kinds)))
                .order_by(Activity.occurred_at.desc(), Activity.id.desc())
                .limit(limit)
            ).scalars()
        )
