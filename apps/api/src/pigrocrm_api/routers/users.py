from uuid import UUID

from fastapi import APIRouter, status

from pigrocrm.core.auth.schemas import UserCreate, UserRead, UserUpdate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.timetracking.schemas import UserRatesUpdate
from pigrocrm.core.timetracking.service import TimeEntryService
from pigrocrm_api.deps import ActorDep, SessionDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/users", tags=["users"], responses=PROBLEM_RESPONSES)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create(data: UserCreate, session: SessionDep, actor: ActorDep) -> UserRead:
    return UserService(session).create(data, actor)


@router.get("", response_model=list[UserRead])
def list_users(session: SessionDep, actor: ActorDep) -> list[UserRead]:
    return UserService(session).list(actor)


@router.patch("/{user_id}", response_model=UserRead)
def update(user_id: UUID, data: UserUpdate, session: SessionDep, actor: ActorDep) -> UserRead:
    return UserService(session).update(user_id, data, actor)


@router.put("/{user_id}/rates", status_code=status.HTTP_204_NO_CONTENT)
def set_user_rates(
    user_id: UUID, data: UserRatesUpdate, session: SessionDep, actor: ActorDep
) -> None:
    """On `TimeEntryService`, not on `UserService`: see the method's own docstring and
    "Contradictions" item 4 -- §11 fixes the audited surface to three service classes
    and this is one of the ten names that must be excluded from MCP by name."""
    TimeEntryService(session).update_user_rates(user_id, data, actor)
