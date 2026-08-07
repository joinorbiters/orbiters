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
    # join_transaction_mode="create_savepoint" is load-bearing, not optional -- see
    # packages/core/tests/conftest.py's identical `db_session` fixture, established
    # in Task 2 specifically because its absence lets `session.rollback()` propagate
    # to the real, externally-managed transaction instead of nesting inside it. This
    # was dormant here because no MCP-side code ever called `session.rollback()`
    # across more than one tool call sharing this session -- until the final review's
    # item 6 fix made `_guard` roll back on every exception, which surfaced it
    # immediately: a blocked `archive_customer` call's `Conflict` rolling back with
    # this parameter absent silently discarded the customer and deal an earlier,
    # already-committed tool call in the *same test* had created. Confirmed directly
    # by reproducing it with this parameter removed and watching two already-
    # committed rows disappear after an unrelated later rollback.
    session = session_factory(mcp_engine)(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def server(mcp_session: Session):
    return build_server(lambda: mcp_session, lambda: ADMIN)
