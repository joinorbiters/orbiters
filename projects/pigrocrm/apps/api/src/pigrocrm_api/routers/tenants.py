"""Signing up for a space: the second public write in the API, after Orbiters.

No `ActorDep`: the person has no account anywhere yet, which is the point. The router
works on the registry database (`TenantsRegistryDep`), never on a space, and answers
only for the root installation -- under `/<slug>/api/tenants` it is not registered
differently, but the page never offers it there, and a space creating spaces is not a
thing this product means.
"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel

from pigrocrm.core.tenants import TenantAvailability, TenantRead, TenantService, TenantSignup
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
    if not presented or not secrets.compare_digest(presented, settings.registry_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token non valido")
    return TenantService(registry, settings).list()


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
