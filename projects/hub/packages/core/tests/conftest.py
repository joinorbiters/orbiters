"""A real Postgres per session, brought to `head` by this package's own migrations.

Not `create_all`: the schema the tests run against is the one the migrations produce,
so a table the model declares and the migration forgets is a failing test here rather
than a surprise on the server.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from orbiters_core.config import Settings
from orbiters_core.db import create_engine_from_settings, session_factory
from orbiters_core.migrate import upgrade_to_head


def settings_for(url: str) -> Settings:
    return Settings(database_url=url, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture(scope="session")
def hub_engine() -> Iterator[Engine]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade_to_head(url)
        engine = create_engine_from_settings(settings_for(url))
        yield engine
        engine.dispose()


@pytest.fixture
def hub_session(hub_engine: Engine) -> Iterator[Session]:
    """Committed writes, wiped after each test: `SignupService.subscribe` commits on its
    own, so a rolled-back outer transaction would not isolate anything."""
    session = session_factory(hub_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("DELETE FROM signups"))
        session.commit()
        session.close()
