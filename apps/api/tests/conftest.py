from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from pigrocrm.core.actor import Actor, Role
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.db import Base, create_engine_from_settings, session_factory
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm_api.deps import get_session, get_storage
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
    # join_transaction_mode="create_savepoint" is load-bearing, not optional -- see
    # packages/core/tests/conftest.py's identical `db_session` fixture, established
    # in Task 2 specifically because its absence lets `session.rollback()` propagate
    # to the real, externally-managed transaction instead of nesting inside it: any
    # test that exercises a DomainError-then-continue sequence across more than one
    # request sharing this session would otherwise lose every earlier commit the
    # moment something later in the same test rolls back -- confirmed directly by
    # reproducing it with this parameter removed and watching two already-committed
    # rows disappear after an unrelated later rollback.
    session = session_factory(api_engine)(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(api_session: Session, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: api_session
    # Documents/templates tests upload and download real bytes; without this override
    # `get_storage` falls through to `storage_from_settings(get_settings())`, which
    # defaults to a `LocalFileStorage` rooted at the repository's own `./var/documents`
    # -- writing real files into the working tree on every test run, left behind for
    # git to notice. A fresh `tmp_path` per test keeps storage exactly as isolated as
    # the database already is (`api_session`'s own rolled-back transaction).
    app.dependency_overrides[get_storage] = lambda: LocalFileStorage(tmp_path)
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


def _client_as(client: TestClient, session: Session, *, email: str, ruolo: Role) -> TestClient:
    """The same shape as `admin_user`/`logged_in` above, generalised over `ruolo` so a
    router's own `actor.require_write`/`actor.require_admin` gate can be exercised
    over real HTTP -- not only at the service layer, where every existing test in
    this suite already covers it."""
    UserService(session).create(
        UserCreate(email=email, password=ADMIN_PASSWORD, nome="Test", ruolo=ruolo),
        Actor.system(),
    )
    response = client.post("/api/auth/login", json={"email": email, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def readonly_client(client: TestClient, api_session: Session) -> TestClient:
    return _client_as(client, api_session, email="readonly@pigro.it", ruolo="readonly")


@pytest.fixture
def collaborator_client(client: TestClient, api_session: Session) -> TestClient:
    return _client_as(client, api_session, email="collaboratore@pigro.it", ruolo="collaboratore")
