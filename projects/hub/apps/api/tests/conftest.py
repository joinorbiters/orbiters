from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from orbiters_api.deps import get_session
from orbiters_api.main import create_app
from orbiters_api.routers.signups import reset_signup_rate_limit
from orbiters_core.config import Settings, get_settings
from orbiters_core.db import create_engine_from_settings, session_factory
from orbiters_core.migrate import upgrade_to_head


@pytest.fixture(scope="session")
def api_engine() -> Iterator[Engine]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        url = container.get_connection_url()
        upgrade_to_head(url)
        engine = create_engine_from_settings(Settings(database_url=url, _env_file=None))  # type: ignore[call-arg]
        yield engine
        engine.dispose()


@pytest.fixture
def api_session(api_engine: Engine) -> Iterator[Session]:
    session = session_factory(api_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("DELETE FROM signups"))
        session.commit()
        session.close()


@pytest.fixture
def client(api_session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: api_session
    # Declared, never inherited from a developer's `.env`: no pixel unless a test says so.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)  # type: ignore[call-arg]
    # The limiter counts requests per process, so one test's posts would otherwise be
    # spent out of the next test's budget.
    reset_signup_rate_limit()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
