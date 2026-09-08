from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.timetracking.schemas import (
    TimeEntryCreate,
    TimeEntryListQuery,
    TimeEntryPage,
    TimeEntryRead,
    TimeEntryUpdate,
)
from pigrocrm.core.timetracking.service import TimeEntryService
from pigrocrm.core.validation import SafeStr
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES
from pigrocrm_api.query_params import CUSTOM_QUERY_DESCRIPTION, parse_custom_filter

router = APIRouter(prefix="/api/time-entries", tags=["time-entries"], responses=PROBLEM_RESPONSES)


@router.post("", response_model=TimeEntryRead, status_code=status.HTTP_201_CREATED)
def create(data: TimeEntryCreate, session: SessionDep, actor: ActorDep) -> TimeEntryRead:
    return TimeEntryService(session).create(data, actor)


@router.get("", response_model=TimeEntryPage)
def list_time_entries(
    session: SessionDep,
    actor: ActorDep,
    deal_id: Annotated[UUID | None, Query()] = None,
    user_id: Annotated[UUID | None, Query()] = None,
    da: Annotated[date | None, Query(description="Data minima, YYYY-MM-DD")] = None,
    a: Annotated[date | None, Query(description="Data massima, YYYY-MM-DD")] = None,
    fatturabile: Annotated[bool | None, Query()] = None,
    fatturato: Annotated[
        bool | None,
        Query(description="true = già su una riga di fattura; false = da fatturare"),
    ] = None,
    # SafeStr on the parameter itself, not only on a schema field: these are ordinary
    # query parameters, so the guard has to sit here for FastAPI's own validation to
    # reject a NUL byte as a 422 before TimeEntryListQuery is hand-built below --
    # identical to `list_deals` in routers/deals.py.
    custom: Annotated[list[SafeStr] | None, Query(description=CUSTOM_QUERY_DESCRIPTION)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> TimeEntryPage:
    query = TimeEntryListQuery(
        deal_id=deal_id,
        user_id=user_id,
        da=da,
        a=a,
        fatturabile=fatturabile,
        fatturato=fatturato,
        custom=parse_custom_filter(custom),
        limit=limit,
        cursor=cursor,
    )
    return TimeEntryService(session).list(query, actor)


@router.get("/{entry_id}", response_model=TimeEntryRead)
def get(entry_id: UUID, session: SessionDep, actor: ActorDep) -> TimeEntryRead:
    return TimeEntryService(session).get(entry_id, actor)


@router.patch("/{entry_id}", response_model=TimeEntryRead)
def update(
    entry_id: UUID, data: TimeEntryUpdate, session: SessionDep, actor: ActorDep
) -> TimeEntryRead:
    return TimeEntryService(session).update(entry_id, data, actor)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(entry_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    TimeEntryService(session).soft_delete(entry_id, actor)


@router.post("/{entry_id}/restore", response_model=TimeEntryRead)
def restore(entry_id: UUID, session: SessionDep, actor: ActorDep) -> TimeEntryRead:
    return TimeEntryService(session).restore(entry_id, actor)
