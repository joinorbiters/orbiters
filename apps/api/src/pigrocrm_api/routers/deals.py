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
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES
from pigrocrm_api.query_params import CUSTOM_QUERY_DESCRIPTION, parse_custom_filter

router = APIRouter(prefix="/api/deals", tags=["deals"], responses=PROBLEM_RESPONSES)


class MoveStageRequest(BaseModel):
    stage_id: UUID


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
