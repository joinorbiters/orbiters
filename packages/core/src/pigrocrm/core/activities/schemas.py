from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: UUID
    kind: str
    actor_id: UUID | None
    actor_type: str
    payload: dict[str, Any]
    occurred_at: datetime
