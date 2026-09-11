"""Signing up for a space: the second public write in the API, after Orbiters.

No `ActorDep`: the person has no account anywhere yet, which is the point. The router
works on the registry database (`TenantsRegistryDep`), never on a space, and answers
only for the root installation -- under `/<slug>/api/tenants` it is not registered
differently, but the page never offers it there, and a space creating spaces is not a
thing this product means.
"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, EmailStr

from pigrocrm.core.tenants import (
    TenantAvailability,
    TenantRead,
    TenantService,
    TenantSignup,
    lookup_member,
)
from pigrocrm_api.deps import SettingsDep, TenantsRegistryDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

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


class MemberAnswer(BaseModel):
    """What the signup learns about an address before the person has an account: whether
    the Orbiters hub knows them as a community member, their two names if so, and the
    spaces the registry already holds in that name."""

    membro: bool
    nome: str | None
    cognome: str | None
    spazi: list[str]


# Declared before `/{slug}/disponibile` so `membro` is never read as a space's name.
@router.get("/membro", response_model=MemberAnswer)
def member(
    email: Annotated[EmailStr, Query()], registry: TenantsRegistryDep, settings: SettingsDep
) -> MemberAnswer:
    """Whether an address belongs to an Orbiters community member, and which spaces it
    already owns here (ORB-173). No auth, like the signup itself: the person has no
    account yet. The hub is asked with `PIGROCRM_REGISTRY_TOKEN` at `PIGROCRM_HUB_URL`
    and given five seconds; unreachable, unconfigured or refusing, the answer is
    `membro: false` and the signup goes on. `spazi` comes from this installation's own
    registry and answers even when the hub does not."""
    address = str(email).strip().lower()
    found = lookup_member(settings, address)
    return MemberAnswer(
        membro=found.membro,
        nome=found.nome,
        cognome=found.cognome,
        spazi=TenantService(registry, settings).slugs_for_owner(address),
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
    data: TenantSignup, registry: TenantsRegistryDep, settings: SettingsDep, response: Response
) -> TenantRead:
    """Creates the space: a registry row, a migrated database, its first admin. 409 when
    the name is taken, 422 when it is malformed or reserved or the password too short.
    The `Location` header is where the person logs in next."""
    tenant = TenantService(registry, settings).provision(data)
    response.headers["Location"] = f"/{tenant.slug}/app/login"
    return tenant
