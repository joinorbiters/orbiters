"""The admin area's API: a login, and the lists behind it.

One cookie, `orbiters_admin`, opaque and httpOnly, resolved against `admin_sessions` on
every request (`deps.get_admin`). The login shares the public token bucket, so a
password guess costs the same budget as a signup flood. Everything under this router
reads or moves rows other people wrote; nothing here writes on their behalf.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, EmailStr

from orbiters_api.deps import ADMIN_COOKIE, AdminDep, SessionDep, SettingsDep
from orbiters_api.ratelimit import spend_one
from orbiters_core.admin import AdminRead, AdminService
from orbiters_core.companies import CompanyService
from orbiters_core.freelancers import FreelancerService
from orbiters_core.schemas import (
    CompanyList,
    CompanyRead,
    FreelancerList,
    FreelancerRead,
    SignupList,
    StatusChange,
)
from orbiters_core.service import SignupService

router = APIRouter(prefix="/api/hub", tags=["hub-admin"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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
    # ASCII-safe filename: the browser reads it, and a quote or a newline in a name the
    # applicant chose must not become a header injection.
    safe = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in cv.filename) or "cv.pdf"
    return Response(
        content=cv.content,
        media_type=cv.mime,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


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


@router.get("/signups", response_model=SignupList)
def list_signups(_: AdminDep, session: SessionDep, limit: Limit = 100) -> SignupList:
    return SignupService(session).list_recent(limit=limit)
