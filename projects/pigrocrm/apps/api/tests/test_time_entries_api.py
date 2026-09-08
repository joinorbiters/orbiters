"""The HTTP surface, thin by design: validate the body, resolve the Actor, call the
service, serialise. Every assertion here is about the wire -- statuses, problem
documents, and Decimal-as-string -- never about business rules, which are proven in
packages/core.
"""

from typing import Any

from fastapi.testclient import TestClient


def _second_actor(admin_client: TestClient, ruolo: str) -> TestClient:
    """A genuinely independent session, not `admin_client`'s own cookie jar. Copied
    from `test_invoices_api.py`'s helper of the same name and purpose -- see its
    docstring for why `logged_in` and `collaborator_client` cannot both be requested
    in the same test."""
    email = f"{ruolo}-{id(admin_client)}@pigro.it"
    created = admin_client.post(
        "/api/users",
        json={"email": email, "password": "supersegreta1", "nome": "Test", "ruolo": ruolo},
    )
    assert created.status_code == 201, created.text
    client = TestClient(admin_client.app, base_url="https://testserver")
    response = client.post("/api/auth/login", json={"email": email, "password": "supersegreta1"})
    assert response.status_code == 200, response.text
    return client


def _seed_pipeline(logged_in: TestClient) -> None:
    assert logged_in.post("/api/pipeline-stages/seed").status_code == 200


def _seed_deal_and_user(logged_in: TestClient) -> tuple[str, str]:
    _seed_pipeline(logged_in)
    customer = logged_in.post("/api/customers", json={"ragione_sociale": "ACME Srl"})
    assert customer.status_code == 201, customer.text
    deal = logged_in.post(
        "/api/deals", json={"nome": "Progetto", "customer_id": customer.json()["id"]}
    )
    assert deal.status_code == 201, deal.text
    user = logged_in.post(
        "/api/users",
        json={
            "email": "worker@pigro.it",
            "password": "supersegreta1",
            "nome": "Worker",
            "ruolo": "collaboratore",
        },
    )
    assert user.status_code == 201, user.text
    return deal.json()["id"], user.json()["id"]


def test_post_creates_and_returns_decimals_as_strings(logged_in: TestClient) -> None:
    """`Decimal` serialises to a JSON string, never a float -- which is exactly what
    lets the frontend read the digits instead of routing them through a binary float.
    Asserted on the raw text, because `response.json()` would already have parsed it."""
    deal_id, user_id = _seed_deal_and_user(logged_in)
    response = logged_in.post(
        "/api/time-entries",
        json={
            "deal_id": deal_id,
            "user_id": user_id,
            "data": "2026-03-10",
            "ore": "3.50",
            "descrizione": "Sviluppo",
            "tariffa_applicata": "80.000000",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ore"] == "3.50"
    assert body["tariffa_applicata"] == "80.000000"
    assert body["valore_riga"] == "280.00"
    assert '"ore":"3.50"' in response.text.replace(" ", "")


def test_a_closed_period_is_a_409_problem_document_naming_the_month(
    logged_in: TestClient,
) -> None:
    deal_id, user_id = _seed_deal_and_user(logged_in)
    assert logged_in.post("/api/period-locks", json={"anno": 2026, "mese": 3}).status_code == 201
    response = logged_in.post(
        "/api/time-entries",
        json={
            "deal_id": deal_id,
            "user_id": user_id,
            "data": "2026-03-10",
            "ore": "1.00",
            "descrizione": "x",
        },
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == "conflict"
    assert problem["mese"] == 3 and problem["anno"] == 2026
    assert "marzo 2026" in problem["detail"]


def test_a_future_date_is_a_422_naming_the_field(logged_in: TestClient) -> None:
    deal_id, user_id = _seed_deal_and_user(logged_in)
    response = logged_in.post(
        "/api/time-entries",
        json={
            "deal_id": deal_id,
            "user_id": user_id,
            "data": "2099-01-01",
            "ore": "1.00",
            "descrizione": "x",
        },
    )
    assert response.status_code == 422
    assert response.json()["field"] == "data"


def test_over_range_hours_are_refused_before_the_database(logged_in: TestClient) -> None:
    """`ore = 80` is the comma slip that means 8,0. Bounded on the schema so it comes
    back as a clean 422 rather than reaching the CHECK as a raw IntegrityError."""
    deal_id, user_id = _seed_deal_and_user(logged_in)
    response = logged_in.post(
        "/api/time-entries",
        json={
            "deal_id": deal_id,
            "user_id": user_id,
            "data": "2026-03-10",
            "ore": "80.00",
            "descrizione": "x",
        },
    )
    assert response.status_code == 422


def test_the_list_is_bounded_and_paginated(logged_in: TestClient) -> None:
    assert logged_in.get("/api/time-entries", params={"limit": 500}).status_code == 422
    ok = logged_in.get("/api/time-entries", params={"limit": 200})
    assert ok.status_code == 200
    assert set(ok.json()) == {"items", "next_cursor"}


def test_recalculate_requires_admin(logged_in: TestClient) -> None:
    deal_id, _ = _seed_deal_and_user(logged_in)
    collaborator = _second_actor(logged_in, "collaboratore")
    response = collaborator.post(
        f"/api/deals/{deal_id}/rates/recalculate",
        json={"da": "2026-03-01", "a": "2026-03-31"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_the_openapi_document_describes_the_new_routes(logged_in: TestClient) -> None:
    """The frontend client is generated from this document, so a route missing here is
    a route the UI cannot call with types."""
    paths: dict[str, Any] = logged_in.get("/openapi.json").json()["paths"]
    for path in (
        "/api/time-entries",
        "/api/time-entries/{entry_id}",
        "/api/deals/{deal_id}/time-entries",
        "/api/deals/{deal_id}/time-summary",
        "/api/deals/{deal_id}/rates",
        "/api/costs",
        "/api/cost-categories",
        "/api/period-locks",
        "/api/users/{user_id}/rates",
    ):
        assert path in paths, path
