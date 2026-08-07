from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm_mcp.server import build_server

ADMIN = Actor(id=None, type="mcp", role="admin")


@pytest.fixture(scope="session")
def mcp_engine() -> Iterator[Engine]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        engine = create_engine_from_settings(Settings(database_url=container.get_connection_url()))
        import pigrocrm.core.models_registry  # noqa: F401

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def mcp_session(mcp_engine: Engine) -> Iterator[Session]:
    connection = mcp_engine.connect()
    transaction = connection.begin()
    session = session_factory(mcp_engine)(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def server(mcp_session: Session):
    return build_server(lambda: mcp_session, lambda: ADMIN)
