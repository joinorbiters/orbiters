from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.activities.repository import ActivityRepository
from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.actor import Actor


class ActivityService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = ActivityRepository(session)

    def record(
        self,
        entity_type: str,
        entity_id: UUID,
        kind: str,
        actor: Actor,
        payload: dict[str, Any] | None = None,
    ) -> Activity:
        """Flushes but never commits: it joins the caller's transaction so a timeline
        entry can never survive a change that was rolled back."""
        return self.repo.add(
            Activity(
                entity_type=entity_type,
                entity_id=entity_id,
                kind=kind,
                actor_id=actor.id,
                actor_type=actor.type,
                payload=payload or {},
            )
        )

    def timeline(self, entity_type: str, entity_id: UUID, limit: int = 50) -> list[ActivityRead]:
        return [
            ActivityRead.model_validate(a)
            for a in self.repo.timeline(entity_type, entity_id, limit)
        ]
