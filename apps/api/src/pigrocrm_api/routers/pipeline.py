from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.pipeline.schemas import (
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
)
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/pipeline-stages", tags=["pipeline"], responses=PROBLEM_RESPONSES)


@router.post("", response_model=PipelineStageRead, status_code=status.HTTP_201_CREATED)
def create(data: PipelineStageCreate, session: SessionDep, actor: ActorDep) -> PipelineStageRead:
    return PipelineService(session).create(data, actor)


@router.get("", response_model=list[PipelineStageRead])
def list_stages(session: SessionDep, actor: ActorDep) -> list[PipelineStageRead]:
    return PipelineService(session).list()


@router.patch("/{stage_id}", response_model=PipelineStageRead)
def update(
    stage_id: UUID, data: PipelineStageUpdate, session: SessionDep, actor: ActorDep
) -> PipelineStageRead:
    return PipelineService(session).update(stage_id, data, actor)


@router.delete("/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(stage_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    """Refuses (409) if any deal, archived or not, still points at this stage."""
    PipelineService(session).delete(stage_id, actor)


@router.post("/seed", response_model=list[PipelineStageRead])
def seed(session: SessionDep, actor: ActorDep) -> list[PipelineStageRead]:
    """The admin check lives in `PipelineService.seed_defaults` itself now, not
    here -- see that method's docstring. This router is back to the same
    validate/resolve/call/serialize shape as every other endpoint."""
    return PipelineService(session).seed_defaults(actor)


@router.get("/{stage_id}/timeline", response_model=list[ActivityRead])
def timeline(
    stage_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityRead]:
    """Administrators only, matching who may change a stage. Deliberately still
    answerable after the stage is gone: `delete` is the one hard DELETE in the domain,
    and the entry it leaves is the only remaining record that the stage existed."""
    actor.require_admin("read_pipeline_stage_timeline")
    return ActivityService(session).timeline("pipeline_stage", stage_id, limit)
