from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.deals.schemas import (
    DealCreate,
    DealListQuery,
    DealPage,
    DealRead,
    DealUpdate,
)
from pigrocrm.core.deals.service import DealService
from pigrocrm.core.timetracking.schemas import (
    DealRateUpdate,
    DealTimeSummary,
    RateDescription,
    RecalculateRatesRequest,
    TimeEntryListQuery,
    TimeEntryPage,
)
from pigrocrm.core.timetracking.service import TimeEntryService
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES
from pigrocrm_api.query_params import CUSTOM_QUERY_DESCRIPTION, parse_custom_filter

router = APIRouter(prefix="/api/deals", tags=["deals"], responses=PROBLEM_RESPONSES)


class MoveStageRequest(BaseModel):
    stage_id: UUID


class RecalculateResponse(BaseModel):
    """`voci_aggiornate` rather than a bare integer: the UI says "12 voci aggiornate",
    and a naked number in a JSON body is a value nobody can label."""

    voci_aggiornate: int


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
def create(data: DealCreate, session: SessionDep, actor: ActorDep) -> DealRead:
    return DealService(session).create(data, actor)


@router.get("", response_model=DealPage)
def list_deals(
    session: SessionDep,
    actor: ActorDep,
    # SafeStr: see the identical comment on list_customers (routers/customers.py)
    # -- these are ordinary query parameters, not Create/Update schema fields, so
    # the guard has to sit on the parameter itself for FastAPI's own validation to
    # catch it as a 422 before DealListQuery is hand-built below.
    search: Annotated[SafeStr | None, Query()] = None,
    customer_id: Annotated[UUID | None, Query()] = None,
    stage_id: Annotated[UUID | None, Query()] = None,
    custom: Annotated[list[SafeStr] | None, Query(description=CUSTOM_QUERY_DESCRIPTION)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> DealPage:
    query = DealListQuery(
        search=search,
        customer_id=customer_id,
        stage_id=stage_id,
        custom=parse_custom_filter(custom),
        limit=limit,
        cursor=cursor,
    )
    return DealService(session).list(query, actor)


@router.get("/{deal_id}", response_model=DealRead)
def get(deal_id: UUID, session: SessionDep, actor: ActorDep) -> DealRead:
    return DealService(session).get(deal_id, actor)


@router.patch("/{deal_id}", response_model=DealRead)
def update(deal_id: UUID, data: DealUpdate, session: SessionDep, actor: ActorDep) -> DealRead:
    return DealService(session).update(deal_id, data, actor)


@router.patch("/{deal_id}/stage", response_model=DealRead)
def move_stage(
    deal_id: UUID, data: MoveStageRequest, session: SessionDep, actor: ActorDep
) -> DealRead:
    """Backs the Kanban drag. Optimistic on the client, authoritative here."""
    return DealService(session).move_stage(deal_id, data.stage_id, actor)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(deal_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    DealService(session).soft_delete(deal_id, actor)


@router.post("/{deal_id}/restore", response_model=DealRead)
def restore(deal_id: UUID, session: SessionDep, actor: ActorDep) -> DealRead:
    return DealService(session).restore(deal_id, actor)


@router.get("/{deal_id}/timeline", response_model=list[ActivityRead])
def timeline(
    deal_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityRead]:
    return ActivityService(session).timeline("deal", deal_id, limit)


@router.get("/{deal_id}/time-entries", response_model=TimeEntryPage)
def deal_time_entries(
    deal_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    da: Annotated[date | None, Query()] = None,
    a: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> TimeEntryPage:
    return TimeEntryService(session).list(
        TimeEntryListQuery(deal_id=deal_id, da=da, a=a, limit=limit, cursor=cursor), actor
    )


@router.get("/{deal_id}/time-summary", response_model=DealTimeSummary)
def deal_time_summary(deal_id: UUID, session: SessionDep, actor: ActorDep) -> DealTimeSummary:
    return TimeEntryService(session).deal_summary(deal_id, actor)


@router.get("/{deal_id}/rates", response_model=RateDescription)
def deal_rates(
    deal_id: UUID, user_id: Annotated[UUID, Query()], session: SessionDep, actor: ActorDep
) -> RateDescription:
    """What a new entry would freeze right now. Shown next to the hours field so the
    rate is visible before saving, not discovered after."""
    return TimeEntryService(session).describe_rates(deal_id, user_id, actor)


@router.put("/{deal_id}/rate", status_code=status.HTTP_204_NO_CONTENT)
def set_deal_rate(
    deal_id: UUID, data: DealRateUpdate, session: SessionDep, actor: ActorDep
) -> None:
    TimeEntryService(session).update_deal_rate(deal_id, data, actor)


@router.post("/{deal_id}/rates/recalculate", response_model=RecalculateResponse)
def recalculate_rates(
    deal_id: UUID, data: RecalculateRatesRequest, session: SessionDep, actor: ActorDep
) -> RecalculateResponse:
    return RecalculateResponse(
        voci_aggiornate=TimeEntryService(session).recalculate_rates(deal_id, data, actor)
    )
