"""The registry database, and the name of each space's own database."""

from sqlalchemy import Engine
from sqlalchemy.engine import URL, make_url

from pigrocrm.core.config import Settings
from pigrocrm.core.db.sidecar import ensure_sidecar_database, sidecar_url
from pigrocrm.core.tenants.models import TenantsBase

DEFAULT_DATABASE_NAME = "pigrocrm_tenants"
# Postgres identifiers are 63 bytes; a 32-character slug fits with room to spare.
TENANT_DATABASE_PREFIX = "pigro_t_"


def tenants_database_url(settings: Settings) -> URL:
    return sidecar_url(settings, settings.tenants_database_url, DEFAULT_DATABASE_NAME)


def ensure_tenants_database(settings: Settings) -> Engine:
    """Idempotent. The registry exists and has its table when this returns."""
    return ensure_sidecar_database(settings, tenants_database_url(settings), TenantsBase.metadata)


def tenant_database_name(slug: str) -> str:
    """`pigro_t_<slug>` with hyphens as underscores: an identifier that needs no quoting
    and cannot collide with `pigrocrm`, `orbiters` or the registry."""
    return TENANT_DATABASE_PREFIX + slug.replace("-", "_")


def tenant_database_url(settings: Settings, db_name: str) -> URL:
    """A space's database lives on the CRM's server, under the CRM's credentials."""
    return make_url(settings.database_url).set(database=db_name)
