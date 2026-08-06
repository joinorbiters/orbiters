from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm_api.deps import get_session
from pigrocrm_api.main import create_app

ADMIN_EMAIL = "admin@pigro.it"
ADMIN_PASSWORD = "supersegreta1"
# Obviously a placeholder, but >= 32 characters: Settings.jwt_secret now rejects
# anything shorter (see pigrocrm.core.config), so a short literal here would fail at
# fixture setup rather than merely warn.
TEST_JWT_SECRET = "test-secret-for-the-api-test-suite-only"


@pytest.fixture(scope="session")
def api_engine() -> Iterator[Engine]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        settings = Settings(database_url=container.get_connection_url(), jwt_secret=TEST_JWT_SECRET)
        get_settings.cache_clear()
        engine = create_engine_from_settings(settings)
        import pigrocrm.core.models_registry  # noqa: F401

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def api_session(api_engine: Engine) -> Iterator[Session]:
    connection = api_engine.connect()
    transaction = connection.begin()
    session = session_factory(api_engine)(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(api_session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: api_session
    # The login/refresh cookies are `Secure` on purpose (production sits behind TLS
    # termination) and httpx's cookie jar honours that against the request's URL
    # scheme -- over the default "http://testserver" it would store the cookie but
    # never send it back, so every later request would look unauthenticated. Using an
    # "https://" base_url exercises the real cookie policy instead of weakening it.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


@pytest.fixture
def admin_user(api_session: Session):
    return UserService(api_session).create(
        UserCreate(email=ADMIN_EMAIL, password=ADMIN_PASSWORD, nome="Admin", ruolo="admin"),
        Actor.system(),
    )


@pytest.fixture
def logged_in(client: TestClient, admin_user) -> TestClient:
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return client
