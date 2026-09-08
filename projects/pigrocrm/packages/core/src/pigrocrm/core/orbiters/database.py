"""The `orbiters` database: found or created, then given its one table.

Outside Alembic on purpose -- see `db/sidecar.py`, which holds the mechanics shared with
the tenant registry.
"""

from sqlalchemy import Engine, text
from sqlalchemy.engine import URL

from pigrocrm.core.config import Settings
from pigrocrm.core.db.sidecar import ensure_sidecar_database, sidecar_url
from pigrocrm.core.orbiters.models import LATE_COLUMNS, OrbitersBase

DEFAULT_DATABASE_NAME = "orbiters"


def orbiters_database_url(settings: Settings) -> URL:
    """`PIGROCRM_ORBITERS_DATABASE_URL` when set; otherwise the CRM's own URL with only
    the database name swapped, so the compose stack needs no second variable."""
    return sidecar_url(settings, settings.orbiters_database_url, DEFAULT_DATABASE_NAME)


def ensure_orbiters_database(settings: Settings) -> Engine:
    """Idempotent. Returns an engine bound to a database that exists and has the table,
    with every column the model declares today.

    `create_all` creates a missing table but never alters an existing one, and the
    production `signups` table predates every column in `LATE_COLUMNS` (the UTM six,
    then `nome`, `cognome` and `linkedin_url`). The one-line migration this sidecar
    needs is done here, idempotently, rather than by giving a one-table database its own
    Alembic history. Every late column is nullable, so adding one to a table with rows
    in it rewrites nothing and needs no default."""
    engine = ensure_sidecar_database(
        settings, orbiters_database_url(settings), OrbitersBase.metadata
    )
    with engine.begin() as connection:
        for column, width in LATE_COLUMNS:
            connection.execute(
                text(f"ALTER TABLE signups ADD COLUMN IF NOT EXISTS {column} VARCHAR({width})")
            )
    return engine
