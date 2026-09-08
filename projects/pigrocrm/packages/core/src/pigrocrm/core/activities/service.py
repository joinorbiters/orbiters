from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.activities.repository import ActivityRepository
from pigrocrm.core.activities.sanitize import sanitize_payload
from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import ValidationFailed

# Column widths from activities/models.py. entity_type/kind are literals developers
# write in code, not user input or agent-supplied data, so plain truncation -- not the
# richer sanitize_payload treatment the payload gets -- is enough: nothing meaningful
# is hidden by cutting off a value nobody was going to type out in full anyway.
_ENTITY_TYPE_MAX_LENGTH = 30
_KIND_MAX_LENGTH = 50

# Matches every REST timeline route's own `Query(ge=1, le=200)` exactly (see
# routers/customers.py, people.py, deals.py). Enforced here, not only per-router,
# because the MCP `get_timeline` tool calls straight into this method with a bare
# `limit: int` parameter of its own -- no schema of any kind sits between the tool
# and this call, unlike search_customers/search_people/search_deals, whose `limit`
# is bounded through `*ListQuery`'s own `Field(ge=1, le=200)`. Without this check,
# `-1` reached Postgres raw as `psycopg.errors.InvalidRowCountInLimitClause` ("LIMIT
# must not be negative"), and `10**9` silently returned everything where REST would
# have refused the request outright -- a parity divergence, not only a crash risk.
TIMELINE_LIMIT_MIN = 1
TIMELINE_LIMIT_MAX = 200


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
        entry can never survive a change that was rolled back.

        Exactly because of that, this must be the *last* thing that touches the
        session before the caller's own commit. Never follow it with a call into
        another service's method that commits on its own behalf in the same
        session -- that commit would persist this entry too, even if the caller's own
        transaction is later rolled back, which defeats the guarantee above.

        `payload` is sanitized by `sanitize_payload`, never validated: an audit entry
        must not be able to fail the very change it is recording. See that function's
        docstring for what "sanitized" means here and why rejecting is not an option.
        """
        return self.repo.add(
            Activity(
                entity_type=entity_type[:_ENTITY_TYPE_MAX_LENGTH],
                entity_id=entity_id,
                kind=kind[:_KIND_MAX_LENGTH],
                actor_id=actor.id,
                actor_type=actor.type,
                payload=sanitize_payload(payload or {}),
            )
        )

    def timeline(self, entity_type: str, entity_id: UUID, limit: int = 50) -> list[ActivityRead]:
        if not TIMELINE_LIMIT_MIN <= limit <= TIMELINE_LIMIT_MAX:
            raise ValidationFailed(
                "activity",
                "limit",
                "fuori intervallo",
                expected=f"{TIMELINE_LIMIT_MIN}-{TIMELINE_LIMIT_MAX}",
            )
        return [
            ActivityRead.model_validate(a)
            for a in self.repo.timeline(entity_type, entity_id, limit)
        ]
