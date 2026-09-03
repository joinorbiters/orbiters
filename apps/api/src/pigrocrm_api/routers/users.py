from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from pigrocrm.core.activities.schemas import ActivityRead
from pigrocrm.core.activities.service import ActivityService
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


@router.get("/{user_id}/timeline", response_model=list[ActivityRead])
def timeline(
    user_id: UUID,
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityRead]:
    """The account's whole story: created, renamed, promoted, deactivated -- and every
    personal access token issued, first used, revoked, or still being presented after
    revocation, which `PatService` records against the owning user rather than against
    a per-token entity nobody would think to open.

    Readable by the owner as well as by an administrator, unlike every other endpoint
    on this router. An administrator is the only one who can *change* an account, but
    the owner is the one who needs to see that a token they thought was dead is still
    being tried -- refusing them that would make the alarm useless to the only person
    who can act on it. Anyone else needs to be an administrator: who holds which
    tokens on which account is not a collaborator's business.
    """
    if actor.id != user_id:
        actor.require_admin("read_user_timeline")
    return ActivityService(session).timeline("user", user_id, limit)
