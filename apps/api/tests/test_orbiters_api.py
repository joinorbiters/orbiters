"""`POST /api/orbiters/signups`: public, on its own database, idempotent.

The `orbiters` database is created inside the same Postgres container `api_engine`
starts, through the real `ensure_orbiters_database` path, and the CRM session the
other tests use is never touched by it.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.orbiters import ensure_orbiters_database
from pigrocrm_api.deps import get_orbiters_session


@pytest.fixture(scope="module")
def orbiters_engine(api_engine: Engine) -> Iterator[Engine]:
    settings = Settings(
        database_url=api_engine.url.render_as_string(hide_password=False),
        _env_file=None,  # type: ignore[call-arg]
    )
    engine = ensure_orbiters_database(settings)
    yield engine
    engine.dispose()


@pytest.fixture
def orbiters_client(client: TestClient, orbiters_engine: Engine) -> Iterator[TestClient]:
    session = session_factory(orbiters_engine)()
    client.app.dependency_overrides[get_orbiters_session] = lambda: session  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        session.rollback()
        session.execute(text("DELETE FROM signups"))
        session.commit()
        session.close()


def test_a_visitor_with_no_account_can_sign_up(orbiters_client: TestClient) -> None:
    response = orbiters_client.post("/api/orbiters/signups", json={"email": "Ada@Studio.it"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "ada@studio.it"
    assert body["nuova"] is True
    assert "id" in body and "created_at" in body


def test_the_same_address_again_answers_200_not_an_error(orbiters_client: TestClient) -> None:
    first = orbiters_client.post("/api/orbiters/signups", json={"email": "ada@studio.it"})
    second = orbiters_client.post("/api/orbiters/signups", json={"email": "ADA@studio.it"})
    assert first.status_code == 201
    assert second.status_code == 200, second.text
    assert second.json()["nuova"] is False
    assert second.json()["id"] == first.json()["id"]


def test_an_address_that_is_not_one_is_a_422(orbiters_client: TestClient) -> None:
    response = orbiters_client.post("/api/orbiters/signups", json={"email": "ciao"})
    assert response.status_code == 422


def test_the_list_never_lands_in_the_crm_database(
    orbiters_client: TestClient, api_session: Session
) -> None:
    orbiters_client.post("/api/orbiters/signups", json={"email": "ada@studio.it"})
    assert api_session.execute(text("SELECT to_regclass('signups')")).scalar() is None
