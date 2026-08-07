from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.customers.schemas import (
    CustomerCreate,
    CustomerListQuery,
    CustomerPage,
    CustomerRead,
    CustomerUpdate,
)
from pigrocrm.core.customers.service import CustomerService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/customers", tags=["customers"], responses=PROBLEM_RESPONSES)


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create(data: CustomerCreate, session: SessionDep, actor: ActorDep) -> CustomerRead:
    return CustomerService(session).create(data, actor)


@router.get("", response_model=CustomerPage)
def list_customers(
    session: SessionDep,
    actor: ActorDep,
    search: Annotated[str | None, Query()] = None,
    stato: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> CustomerPage:
    query = CustomerListQuery(search=search, stato=stato, limit=limit, cursor=cursor)
    return CustomerService(session).list(query, actor)


@router.get("/{customer_id}", response_model=CustomerRead)
def get(customer_id: UUID, session: SessionDep, actor: ActorDep) -> CustomerRead:
    return CustomerService(session).get(customer_id, actor)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update(
    customer_id: UUID, data: CustomerUpdate, session: SessionDep, actor: ActorDep
) -> CustomerRead:
    return CustomerService(session).update(customer_id, data, actor)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete(customer_id: UUID, session: SessionDep, actor: ActorDep) -> None:
    """Sets deleted_at. Nothing in this slice removes a row."""
    CustomerService(session).soft_delete(customer_id, actor)


@router.post("/{customer_id}/restore", response_model=CustomerRead)
def restore(customer_id: UUID, session: SessionDep, actor: ActorDep) -> CustomerRead:
    return CustomerService(session).restore(customer_id, actor)


@router.get("/{customer_id}/timeline", response_model=list[ActivityRead])
def timeline(
    customer_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityRead]:
    return ActivityService(session).timeline("customer", customer_id, limit)
