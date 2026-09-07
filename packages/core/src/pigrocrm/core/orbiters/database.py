"""The `orbiters` database: found or created, then given its one table.

Outside Alembic on purpose. `packages/core/migrations` describes the CRM schema and every
self-hosted installation runs it; this database exists only where the Orbiters page is
actually served, and its whole schema is one table. `create_all` on a dedicated
`MetaData` is the honest size of tool for that.
"""

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ProgrammingError

from pigrocrm.core.config import Settings
from pigrocrm.core.orbiters.models import OrbitersBase

DEFAULT_DATABASE_NAME = "orbiters"


def orbiters_database_url(settings: Settings) -> URL:
    """`PIGROCRM_ORBITERS_DATABASE_URL` when set; otherwise the CRM's own URL with only
    the database name swapped, so the compose stack needs no second variable."""
    if settings.orbiters_database_url:
        return make_url(settings.orbiters_database_url)
    return make_url(settings.database_url).set(database=DEFAULT_DATABASE_NAME)


def _admin_url(settings: Settings, target: URL) -> URL:
    """Where to connect in order to run `CREATE DATABASE` for `target`.

    `CREATE DATABASE` needs a connection to *some other* database on the same server.
    When the target lives on the CRM's server, the CRM database is that other one and
    its credentials are known to work. An explicit URL pointing elsewhere falls back
    to Postgres's own maintenance database.
    """
    main = make_url(settings.database_url)
    same_server = (main.host, main.port, main.username) == (
        target.host,
        target.port,
        target.username,
    )
    if same_server and main.database != target.database:
        return main
    return target.set(database="postgres")


def ensure_orbiters_database(settings: Settings) -> Engine:
    """Idempotent. Returns an engine bound to a database that exists and has the table."""
    target = orbiters_database_url(settings)
    if target.database is None:
        raise ValueError("the Orbiters database URL names no database")

    admin = create_engine(_admin_url(settings, target), isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
            ).scalar()
            if exists is None:
                quoted = admin.dialect.identifier_preparer.quote(target.database)
                try:
                    connection.execute(text(f"CREATE DATABASE {quoted}"))
                except ProgrammingError as exc:
                    # Two processes booting at once: one of them loses the race and
                    # finds the database created a moment ago. Anything else is real.
                    if "already exists" not in str(exc):
                        raise
    finally:
        admin.dispose()

    engine = create_engine(target, pool_pre_ping=True, future=True)
    OrbitersBase.metadata.create_all(engine)
    return engine
