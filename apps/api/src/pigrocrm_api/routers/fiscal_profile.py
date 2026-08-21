from fastapi import APIRouter

from pigrocrm.core.fiscal.schemas import FiscalProfileRead, FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(
    prefix="/api/fiscal-profile", tags=["fiscal-profile"], responses=PROBLEM_RESPONSES
)


@router.get("", response_model=FiscalProfileRead)
def get(session: SessionDep, actor: ActorDep) -> FiscalProfileRead:
    return FiscalProfileService(session).get(actor)


@router.put("", response_model=FiscalProfileRead)
def upsert(data: FiscalProfileUpsert, session: SessionDep, actor: ActorDep) -> FiscalProfileRead:
    """Admin only, enforced by the service (`actor.require_admin`), not by a router
    dependency: there is no role dependency in this codebase, and adding one here would
    put the same rule in two places."""
    return FiscalProfileService(session).upsert(data, actor)
