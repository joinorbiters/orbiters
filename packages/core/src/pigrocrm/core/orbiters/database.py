"""The `orbiters` database: found or created, then given its one table.

Outside Alembic on purpose -- see `db/sidecar.py`, which holds the mechanics shared with
the tenant registry.
"""

from sqlalchemy import Engine
from sqlalchemy.engine import URL

from pigrocrm.core.config import Settings
from pigrocrm.core.db.sidecar import ensure_sidecar_database, sidecar_url
from pigrocrm.core.orbiters.models import OrbitersBase

DEFAULT_DATABASE_NAME = "orbiters"


def orbiters_database_url(settings: Settings) -> URL:
    """`PIGROCRM_ORBITERS_DATABASE_URL` when set; otherwise the CRM's own URL with only
    the database name swapped, so the compose stack needs no second variable."""
    return sidecar_url(settings, settings.orbiters_database_url, DEFAULT_DATABASE_NAME)


def ensure_orbiters_database(settings: Settings) -> Engine:
    """Idempotent. Returns an engine bound to a database that exists and has the table."""
    return ensure_sidecar_database(settings, orbiters_database_url(settings), OrbitersBase.metadata)
