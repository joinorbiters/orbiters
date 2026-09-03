from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.fields.schemas import (
    EntityType,
    FieldDefinitionCreate,
    FieldDefinitionRead,
    FieldDefinitionUpdate,
)
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/field-definitions", tags=["fields"], responses=PROBLEM_RESPONSES)


@router.post("", response_model=FieldDefinitionRead, status_code=status.HTTP_201_CREATED)
def create(
    data: FieldDefinitionCreate, session: SessionDep, actor: ActorDep
) -> FieldDefinitionRead:
    return FieldDefinitionService(session).create(data, actor)


@router.get("", response_model=list[FieldDefinitionRead])
def list_fields(
    session: SessionDep,
    actor: ActorDep,
    entity_type: Annotated[EntityType, Query()],
    include_archived: Annotated[bool, Query()] = False,
) -> list[FieldDefinitionRead]:
    return FieldDefinitionService(session).list(entity_type, include_archived=include_archived)


@router.patch("/{field_id}", response_model=FieldDefinitionRead)
def update(
    field_id: UUID, data: FieldDefinitionUpdate, session: SessionDep, actor: ActorDep
) -> FieldDefinitionRead:
    return FieldDefinitionService(session).update(field_id, data, actor)


@router.post("/{field_id}/archive", response_model=FieldDefinitionRead)
def archive(field_id: UUID, session: SessionDep, actor: ActorDep) -> FieldDefinitionRead:
    """Archive, never delete: rows still hold the value in JSONB."""
    return FieldDefinitionService(session).archive(field_id, actor)


@router.post("/{field_id}/unarchive", response_model=FieldDefinitionRead)
def unarchive(field_id: UUID, session: SessionDep, actor: ActorDep) -> FieldDefinitionRead:
    """Symmetric to archive: the stored JSONB values were never touched, only the
    field's visibility changes."""
    return FieldDefinitionService(session).unarchive(field_id, actor)


@router.get("/{field_id}/timeline", response_model=list[ActivityRead])
def timeline(
    field_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityRead]:
    """Administrators only, matching exactly who may change a definition. A rename and
    an archive are separate kinds here, so "it is called something else now" is never
    confused with "it is gone from every form"."""
    actor.require_admin("read_field_definition_timeline")
    return ActivityService(session).timeline("field_definition", field_id, limit)
