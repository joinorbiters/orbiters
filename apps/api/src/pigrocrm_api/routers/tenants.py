"""Signing up for a space: the second public write in the API, after Orbiters.

No `ActorDep`: the person has no account anywhere yet, which is the point. The router
works on the registry database (`TenantsRegistryDep`), never on a space, and answers
only for the root installation -- under `/<slug>/api/tenants` it is not registered
differently, but the page never offers it there, and a space creating spaces is not a
thing this product means.
"""

from fastapi import APIRouter, Response, status

from pigrocrm.core.tenants import TenantAvailability, TenantRead, TenantService, TenantSignup
from pigrocrm_api.deps import SettingsDep, TenantsRegistryDep
from pigrocrm_api.errors import PROBLEM_RESPONSES

router = APIRouter(prefix="/api/tenants", tags=["tenants"], responses=PROBLEM_RESPONSES)


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
