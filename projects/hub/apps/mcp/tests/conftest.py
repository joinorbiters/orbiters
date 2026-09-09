from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.community.postgres import PostgresContainer

from orbiters_core.config import Settings
from orbiters_core.db import create_engine_from_settings, session_factory
from orbiters_core.migrate import upgrade_to_head


@pytest.fixture(scope="session")
def mcp_engine() -> Iterator[Engine]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade_to_head(url)
        engine = create_engine_from_settings(Settings(database_url=url, _env_file=None))  # type: ignore[call-arg]
        yield engine
        engine.dispose()


@pytest.fixture
def factory(mcp_engine: Engine) -> Iterator[sessionmaker[Session]]:
    made = session_factory(mcp_engine)
    yield made
    session = made()
    session.execute(text("DELETE FROM signups"))
    session.commit()
    session.close()
