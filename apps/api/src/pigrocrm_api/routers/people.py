from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.people.schemas import (
    PersonCreate,
    PersonListQuery,
    PersonPage,
    PersonRead,
    PersonUpdate,
)
from pigrocrm.core.people.service import PersonService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/people", tags=["people"], responses=PROBLEM_RESPONSES)


@router.post("", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
def create(data: PersonCreate, session: SessionDep, actor: ActorDep) -> PersonRead:
    return PersonService(session).create(data, actor)


@router.get("", response_model=PersonPage)
def list_people(
    session: SessionDep,
    actor: ActorDep,
    search: Annotated[str | None, Query()] = None,
    customer_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> PersonPage:
    query = PersonListQuery(search=search, customer_id=customer_id, limit=limit, cursor=cursor)
    return PersonService(session).list(query, actor)


@router.get("/{person_id}", response_model=PersonRead)
def get(person_id: UUID, session: SessionDep, actor: ActorDep) -> PersonRead:
    return PersonService(session).get(person_id, actor)


@router.patch("/{person_id}", response_model=PersonRead)
def update(person_id: UUID, data: PersonUpdate, session: SessionDep, actor: ActorDep) -> PersonRead:
    return PersonService(session).update(person_id, data, actor)


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(person_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    PersonService(session).soft_delete(person_id, actor)


@router.post("/{person_id}/restore", response_model=PersonRead)
def restore(person_id: UUID, session: SessionDep, actor: ActorDep) -> PersonRead:
    return PersonService(session).restore(person_id, actor)


@router.get("/{person_id}/timeline", response_model=list[ActivityRead])
def timeline(
    person_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityRead]:
    return ActivityService(session).timeline("person", person_id, limit)
