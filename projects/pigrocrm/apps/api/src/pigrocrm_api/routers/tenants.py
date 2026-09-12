"""Signing up for a space: the second public write in the API, after Orbiters.

No `ActorDep`: the person has no account anywhere yet, which is the point. The router
works on the registry database (`TenantsRegistryDep`), never on a space, and answers
only for the root installation -- under `/<slug>/api/tenants` it is not registered
differently, but the page never offers it there, and a space creating spaces is not a
thing this product means.
"""

import secrets
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import create_engine

from pigrocrm.core.auth.refresh_service import RefreshTokenService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.tokens import issue_access_token
from pigrocrm.core.db.session import session_factory
from pigrocrm.core.mail import welcome_mail
from pigrocrm.core.tenants import (
    TenantAvailability,
    TenantRead,
    TenantService,
    TenantSignup,
    lookup_member,
)
from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url
from pigrocrm_api.deps import ACCESS_COOKIE, REFRESH_COOKIE, SettingsDep, TenantsRegistryDep
from pigrocrm_api.errors import PROBLEM_RESPONSES
from pigrocrm_api.ratelimit import spend_one
from pigrocrm_api.routers.auth import SenderDep, _set_cookie

router = APIRouter(prefix="/api/tenants", tags=["tenants"], responses=PROBLEM_RESPONSES)


class RootSpace(BaseModel):
    """The root installation's own space name (`PIGROCRM_ROOT_SLUG`), or null when the
    root answers only without a prefix."""

    slug: str | None


@router.get("/root", response_model=RootSpace)
def root_space(settings: SettingsDep) -> RootSpace:
    """What the SPA asks under a prefix to learn whether it is the root wearing its own
    name -- in which case its login may still offer to create a space."""
    return RootSpace(slug=settings.root_slug or None)


@router.get("/", response_model=list[TenantRead])
def list_spaces(
    registry: TenantsRegistryDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> list[TenantRead]:
    """Every space in the registry, newest first, for the one caller that holds
    `PIGROCRM_REGISTRY_TOKEN`: the Orbiters hub, whose admin area shows which spaces
    exist and whose they are (ORB-142). Without the token configured the route does not
    exist (404), so nothing says there is a door; with it, a missing or wrong bearer is a
    401. What comes back is the registry row and nothing about the database behind it."""
    if not settings.registry_token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    presented = authorization.removeprefix("Bearer ").strip() if authorization else ""
    # Bytes, not str: Starlette decodes headers as latin-1 and `compare_digest` refuses a
    # `str` with a non-ASCII character, which would turn a stray byte into a 500.
    if not presented or not secrets.compare_digest(
        presented.encode("utf-8"), settings.registry_token.encode("utf-8")
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token non valido")
    return TenantService(registry, settings).list()


class MemberQuestion(BaseModel):
    """The address the signup asks about. In a body, never in the URL: a query string is
    written by the access log and by every proxy on the way, on both hosts."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class MemberAnswer(BaseModel):
    """What the signup learns about an address before the person has an account: whether
    the Orbiters hub knows them as a community member, their two names if so, and how
    many spaces the registry already holds in that name. A count, not the slugs: the
    address is not proven yet, and which spaces are whose is the mail's to tell."""

    membro: bool
    nome: str | None
    cognome: str | None
    spazi: int


# With the other public signup routes: no account exists yet when this is asked.
@router.post("/membro", response_model=MemberAnswer)
def member(
    payload: MemberQuestion, request: Request, registry: TenantsRegistryDep, settings: SettingsDep
) -> MemberAnswer:
    """Whether an address belongs to an Orbiters community member, and how many spaces
    it already owns here (ORB-173). No auth, like the signup itself: the person has no
    account yet, so the route is throttled per client instead. The hub is asked with
    `PIGROCRM_REGISTRY_TOKEN` at `PIGROCRM_HUB_URL` and given five seconds; unreachable,
    unconfigured or refusing, the answer is `membro: false` and the signup goes on.
    `spazi` comes from this installation's own registry and answers even when the hub
    does not."""
    spend_one(request)
    address = str(payload.email).strip().lower()
    found = lookup_member(settings, address)
    return MemberAnswer(
        membro=found.membro,
        nome=found.nome,
        cognome=found.cognome,
        spazi=TenantService(registry, settings).count_for_owner(address),
    )


@router.get("/{slug}/disponibile", response_model=TenantAvailability)
def availability(
    slug: str, registry: TenantsRegistryDep, settings: SettingsDep
) -> TenantAvailability:
    """Whether a name can still be taken, and if not why -- reserved, malformed or in
    use -- in the words the page shows while the person is still typing."""
    return TenantService(registry, settings).availability(slug.strip().lower())


@router.post("/", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def signup(
    data: TenantSignup,
    registry: TenantsRegistryDep,
    settings: SettingsDep,
    response: Response,
    background: BackgroundTasks,
    sender: SenderDep,
) -> TenantRead:
    """Creates the space: a registry row, a migrated database, its first admin, its
    defaults. 409 when the name is taken, 422 when it is malformed or reserved or a
    password is given and too short.

    Registering is entering (spec 2026-09-12 §6.4): the response carries the cookies the
    space's own login would set, at the space's path (the browser accepts them from the
    root's response: same host), and `Location` is the space's home. The first link
    entry of the real owner revokes this session (`MagicLinkService.enter`), which is
    what makes opening it before the address is proven safe. The welcome mail leaves
    after the response when a sender and a public origin exist; without them the space
    is created all the same."""
    tenant = TenantService(registry, settings).provision(data)
    engine = create_engine(
        tenant_database_url(settings, tenant_database_name(tenant.slug)), future=True
    )
    try:
        with session_factory(engine)() as space:
            admin = UserRepository(space).get_by_email(tenant.owner_email)
            if admin is None:  # pragma: no cover - provision just created it
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "spazio senza admin")
            refresh = RefreshTokenService(space).issue(admin.id, settings)
            access = issue_access_token(admin.id, admin.ruolo, settings)
    finally:
        engine.dispose()
    path = f"/{tenant.slug}/"
    _set_cookie(
        response,
        ACCESS_COOKIE,
        access,
        settings.access_token_minutes * 60,
        secure=settings.cookie_secure,
        path=path,
    )
    _set_cookie(
        response,
        REFRESH_COOKIE,
        refresh,
        settings.refresh_token_days * 86400,
        secure=settings.cookie_secure,
        path=path,
    )
    response.headers["Location"] = f"/{tenant.slug}/app/"
    origin = settings.public_url.strip().rstrip("/")
    if sender is not None and origin:
        login_url = f"{origin}/{tenant.slug}/app/login"
        background.add_task(
            sender.send, welcome_mail(tenant.owner_email, data.nome, login_url, membro=data.membro)
        )
    return tenant
