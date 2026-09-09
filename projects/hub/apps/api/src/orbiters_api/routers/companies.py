"""`POST /api/hub/companies`: a company describes what it needs. JSON, public,
rate-limited, mute -- the same three properties as the other two public writes."""

from fastapi import APIRouter, Request, status

from orbiters_api.deps import SessionDep
from orbiters_api.ratelimit import spend_one
from orbiters_core.companies import CompanyService
from orbiters_core.schemas import Ack, CompanyCreate

router = APIRouter(prefix="/api/hub", tags=["hub"])


@router.post("/companies", response_model=Ack, status_code=status.HTTP_201_CREATED)
def request_people(data: CompanyCreate, session: SessionDep, request: Request) -> Ack:
    spend_one(request)
    CompanyService(session).request(data)
    return Ack()
