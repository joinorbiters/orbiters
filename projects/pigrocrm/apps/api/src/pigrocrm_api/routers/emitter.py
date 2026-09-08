from fastapi import APIRouter

from pigrocrm.core.emitter.schemas import EmitterProfileRead, EmitterProfileUpsert
from pigrocrm.core.emitter.service import EmitterProfileService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/emitter", tags=["emitter"], responses=PROBLEM_RESPONSES)


@router.get("", response_model=EmitterProfileRead)
def get(session: SessionDep, actor: ActorDep) -> EmitterProfileRead:
    """404 until it is saved once: an empty profile and an unsaved one are different
    facts, and a document cannot be rendered without it."""
    return EmitterProfileService(session).get(actor)


@router.put("", response_model=EmitterProfileRead)
def upsert(data: EmitterProfileUpsert, session: SessionDep, actor: ActorDep) -> EmitterProfileRead:
    return EmitterProfileService(session).upsert(data, actor)
