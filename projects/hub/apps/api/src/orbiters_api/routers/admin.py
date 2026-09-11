"""The admin area's API: a login, and the lists behind it.

One cookie, `orbiters_admin`, opaque and httpOnly, resolved against `admin_sessions` on
every request (`deps.get_admin`). The login shares the public token bucket, so a
password guess costs the same budget as a signup flood. Everything under this router
reads or moves rows other people wrote, or adds one more admin (ORB-123); nothing here
writes on an applicant's behalf.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from orbiters_api.deps import ADMIN_COOKIE, AdminDep, SessionDep, SettingsDep
from orbiters_api.downloads import cv_response
from orbiters_api.ratelimit import spend_one
from orbiters_core.admin import AdminRead, AdminService
from orbiters_core.comments import CommentService
from orbiters_core.companies import CompanyService
from orbiters_core.freelancers import FreelancerService
from orbiters_core.models import NAME_MAX_LENGTH
from orbiters_core.perks import PerkService
from orbiters_core.schemas import (
    CommentCreate,
    CommentRead,
    CompanyList,
    CompanyRead,
    FreelancerList,
    FreelancerRead,
    GuideStats,
    SignupList,
    StatusChange,
)
from orbiters_core.service import SignupService
from orbiters_core.validation import SafeStr

router = APIRouter(prefix="/api/hub", tags=["hub-admin"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminCreate(BaseModel):
    """The form behind «Amministratori»: the creating admin chooses the password and
    hands it over out of band, as `orbiters createadmin` does (ORB-123). The rules on the
    password and the name live in `AdminService.create`, once, so the CLI and the form
    agree; this only closes what a body can carry that a prompt cannot: a NUL byte, a
    key nobody declared (`attivo` is not for the caller to choose), and a name past the
    column before Postgres sees it."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    nome: SafeStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    password: str


class AdminUpdate(BaseModel):
    """The pencil on a row (ORB-129): each field optional, absent means «keep it». An
    empty password is «keep it» too, since that is what an untouched password field
    sends; a present one goes through the service's ten-character rule. `attivo` is not
    here on purpose: Ivan does not want deactivation from the area yet."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    nome: SafeStr | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    password: str | None = None


@router.post("/auth/login", response_model=AdminRead)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> AdminRead:
    spend_one(request)
    service = AdminService(session, settings)
    admin = service.authenticate(payload.email, payload.password)
    if admin is None:
        # The same sentence for an unknown address, a wrong password and a deactivated
        # admin: the form is not an oracle for who reads this area.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenziali non valide")
    response.set_cookie(
        ADMIN_COOKIE,
        service.open_session(admin.id),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.admin_session_days * 86400,
        path="/",
    )
    return admin


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    AdminService(session, settings).close_session(request.cookies.get(ADMIN_COOKIE))
    response.delete_cookie(ADMIN_COOKIE, path="/")


@router.get("/auth/me", response_model=AdminRead)
def me(admin: AdminDep) -> AdminRead:
    return admin


# ---- the admins ------------------------------------------------------------------------
#
# Who reads this area, one more of them, and a change to one (ORB-123, ORB-129). No
# deactivation and no deletion here, on purpose: the `attivo` flag exists and nothing in
# the area changes it yet.


@router.get("/admins", response_model=list[AdminRead])
def list_admins(_: AdminDep, session: SessionDep, settings: SettingsDep) -> list[AdminRead]:
    return AdminService(session, settings).list()


@router.post("/admins", response_model=AdminRead, status_code=status.HTTP_201_CREATED)
def create_admin(
    _: AdminDep, session: SessionDep, settings: SettingsDep, payload: AdminCreate
) -> AdminRead:
    return AdminService(session, settings).create(payload.email, payload.nome, payload.password)


@router.patch("/admins/{admin_id}", response_model=AdminRead)
def update_admin(
    _: AdminDep,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    admin_id: UUID,
    payload: AdminUpdate,
) -> AdminRead:
    # The caller's own cookie is spared when a new password revokes the row's sessions,
    # so an admin resetting their own password is not logged out by it.
    return AdminService(session, settings).update(
        admin_id,
        nome=payload.nome,
        email=payload.email,
        password=payload.password or None,
        keep_session=request.cookies.get(ADMIN_COOKIE),
    )


# ---- the lists -------------------------------------------------------------------------

Limit = Annotated[int, Query(ge=1, le=500)]


@router.get("/freelancers", response_model=FreelancerList)
def list_freelancers(
    _: AdminDep, session: SessionDep, limit: Limit = 100, stato: str | None = None
) -> FreelancerList:
    return FreelancerService(session).list_recent(limit=limit, stato=stato)


@router.get("/freelancers/{freelancer_id}", response_model=FreelancerRead)
def get_freelancer(_: AdminDep, session: SessionDep, freelancer_id: UUID) -> FreelancerRead:
    return FreelancerService(session).get(freelancer_id)


@router.get("/freelancers/{freelancer_id}/cv")
def download_cv(_: AdminDep, session: SessionDep, freelancer_id: UUID) -> Response:
    cv = FreelancerService(session).cv(freelancer_id)
    return cv_response(cv)


@router.patch("/freelancers/{freelancer_id}", response_model=FreelancerRead)
def move_freelancer(
    _: AdminDep, session: SessionDep, freelancer_id: UUID, change: StatusChange
) -> FreelancerRead:
    return FreelancerService(session).set_status(freelancer_id, change)


@router.get("/companies", response_model=CompanyList)
def list_companies(
    _: AdminDep, session: SessionDep, limit: Limit = 100, stato: str | None = None
) -> CompanyList:
    return CompanyService(session).list_recent(limit=limit, stato=stato)


@router.get("/companies/{company_id}", response_model=CompanyRead)
def get_company(_: AdminDep, session: SessionDep, company_id: UUID) -> CompanyRead:
    return CompanyService(session).get(company_id)


@router.patch("/companies/{company_id}", response_model=CompanyRead)
def move_company(
    _: AdminDep, session: SessionDep, company_id: UUID, change: StatusChange
) -> CompanyRead:
    return CompanyService(session).set_status(company_id, change)


@router.get("/perks/guida", response_model=GuideStats)
def guide_stats(_: AdminDep, session: SessionDep) -> GuideStats:
    """How the guide is doing (ORB-156): every download, the distinct members behind
    them, the last week, and the latest ones by name. Read-only; the rows are written by
    `GET /me/guida` and by nothing else."""
    return PerkService(session).guide_stats()


@router.get("/signups", response_model=SignupList)
def list_signups(_: AdminDep, session: SessionDep, limit: Limit = 100) -> SignupList:
    return SignupService(session).list_recent(limit=limit)


# ---- comments --------------------------------------------------------------------------
#
# Append-only, on the same cookie as everything else here. The author is the admin the
# cookie resolves to: the body carries the text alone, so nobody can sign as somebody
# else. No PATCH and no DELETE on purpose: a thread is a record (ORB-59).


@router.get("/freelancers/{freelancer_id}/comments", response_model=list[CommentRead])
def list_freelancer_comments(
    _: AdminDep, session: SessionDep, freelancer_id: UUID
) -> list[CommentRead]:
    return CommentService(session).list("freelancer", freelancer_id)


@router.post(
    "/freelancers/{freelancer_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_freelancer_comment(
    admin: AdminDep, session: SessionDep, freelancer_id: UUID, payload: CommentCreate
) -> CommentRead:
    return CommentService(session).add("freelancer", freelancer_id, payload.testo, admin.nome)


@router.get("/companies/{company_id}/comments", response_model=list[CommentRead])
def list_company_comments(_: AdminDep, session: SessionDep, company_id: UUID) -> list[CommentRead]:
    return CommentService(session).list("company", company_id)


@router.post(
    "/companies/{company_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_company_comment(
    admin: AdminDep, session: SessionDep, company_id: UUID, payload: CommentCreate
) -> CommentRead:
    return CommentService(session).add("company", company_id, payload.testo, admin.nome)
