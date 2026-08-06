from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.command import upgrade
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

import pigrocrm.core.models_registry  # noqa: F401
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import Base

CORE_ROOT = Path(__file__).resolve().parents[1]

# Autogenerate is known to silently omit exactly these two shapes: a unique index over a
# SQL expression rather than a bare column (`uq_users_email_lower`), and a plain unique
# index on a nullable column (`uq_pipeline_stage_code`). The three GIN indexes are the
# other shape it handles poorly -- losing any of them turns a JSONB containment filter
# into a sequential scan. Named explicitly here so a regression fails with the missing
# index's name instead of a generic metadata diff.
HAND_MAINTAINED_INDEXES = {
    "uq_users_email_lower",
    "uq_pipeline_stage_code",
    "ix_customers_custom_fields",
    "ix_people_custom_fields",
    "ix_deals_custom_fields",
}


def _alembic_config(url: str) -> Config:
    config = Config(str(CORE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(CORE_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _upgrade_to_head(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """`env.py` deliberately ignores whatever URL the `Config` object carries and
    resolves the real one from `get_settings()` instead -- the same single source of
    truth the rest of the application uses, and exactly how the brief's own Step 5 points
    a throwaway container at Alembic (`PIGROCRM_DATABASE_URL=... alembic revision
    --autogenerate`). Pointing a test's container at Alembic means pointing
    `get_settings()` at it the same way: set the environment variable it reads, and clear
    its `lru_cache` so neither a stale default nor a previous test's already-stopped
    container URL leaks into this one.
    """
    monkeypatch.setenv("PIGROCRM_DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        upgrade(_alembic_config(url), "head")
    finally:
        get_settings.cache_clear()


def test_migrations_produce_exactly_the_models_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """A drift between migrations and models is invisible until deploy day, when the
    application meets a table the code does not expect."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        _upgrade_to_head(monkeypatch, url)

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            diff = compare_metadata(context, Base.metadata)
        engine.dispose()

    assert diff == [], f"migrations and models disagree: {diff}"


def test_every_table_the_slice_needs_exists() -> None:
    expected = {
        "users",
        "personal_access_tokens",
        "field_definitions",
        "pipeline_stages",
        "activities",
        "customers",
        "people",
        "deals",
    }
    assert expected <= set(Base.metadata.tables)


def test_hand_maintained_indexes_survive_the_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    """`compare_metadata` (above) already proves migrations and models agree overall, but
    a diff report names a mismatch, not a silent gap -- this test names the exact indexes
    that autogenerate is known to drop, so a future regression fails as a missing name
    instead of a generic diff someone has to go decode."""
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        _upgrade_to_head(monkeypatch, url)

        engine: Engine = create_engine(url)
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
            ).all()
        engine.dispose()

    indexes = {row.indexname: row.indexdef for row in rows}

    missing = HAND_MAINTAINED_INDEXES - set(indexes)
    assert not missing, f"migration did not create these indexes: {missing}"

    # Postgres normalizes the expression to `lower((email)::text)` -- the explicit cast is
    # its own reflection detail, not something to pin exactly; what matters is that this is
    # still a functional index over `email` through `lower()`, not a plain column index.
    email_lower_def = indexes["uq_users_email_lower"]
    assert "UNIQUE" in email_lower_def, "uq_users_email_lower must be a unique index"
    assert "lower(" in email_lower_def and "email" in email_lower_def, (
        f"uq_users_email_lower is not a functional index over lower(email): {email_lower_def}"
    )

    for gin_index in (
        "ix_customers_custom_fields",
        "ix_people_custom_fields",
        "ix_deals_custom_fields",
    ):
        assert "USING gin" in indexes[gin_index], f"{gin_index} was not created as a GIN index"
