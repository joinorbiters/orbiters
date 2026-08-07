from uuid import UUID

from fastapi import APIRouter, status

from pigrocrm.core.pipeline.schemas import (
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
)
from pigrocrm.core.pipeline.service import PipelineService
from pigrocrm_api.deps import ActorDep, SessionDep

router = APIRouter(prefix="/api/pipeline-stages", tags=["pipeline"])


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
    actor.require_admin("seed_pipeline")
    return PipelineService(session).seed_defaults()
