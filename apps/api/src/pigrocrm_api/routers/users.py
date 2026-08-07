from uuid import UUID

from fastapi import APIRouter, status

from pigrocrm.core.auth.schemas import UserCreate, UserRead, UserUpdate
from pigrocrm.core.auth.service import UserService
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
