"""Migration 0001 adopts the table PigroCRM's sidecar left behind, rows included."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

import orbiters_core.models  # noqa: F401
from orbiters_core.db import Base
from orbiters_core.migrate import head_revision, upgrade_to_head


def test_the_migrations_produce_exactly_the_models_schema(hub_engine: Engine) -> None:
    with hub_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], diff


def test_the_production_table_is_adopted_with_its_rows() -> None:
    """The shape `create_all` gave the table on 2026-09-07 plus the columns two
    `ADD COLUMN IF NOT EXISTS` rounds added later, with a row in it: after `upgrade`
    the row is still there, the late columns exist, and the version table is at head."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        engine = create_engine(url, future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE signups (id UUID NOT NULL, email VARCHAR(320) NOT NULL, "
                    "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
                    "utm_source VARCHAR(200), PRIMARY KEY (id))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO signups (id, email) "
                    "VALUES (gen_random_uuid(), 'vecchia@studio.it')"
                )
            )
        upgrade_to_head(url)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM signups")).scalar() == 1
            columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'signups'"
                    )
                ).scalars()
            )
            assert {"nome", "cognome", "linkedin_url", "utm_id"} <= columns
            version = connection.execute(text("SELECT version_num FROM alembic_version"))
            assert version.scalar() == head_revision()
            # And the result is the models' schema, on the adopted table as on a fresh one.
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
            assert diff == [], diff
        engine.dispose()
