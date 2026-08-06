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
