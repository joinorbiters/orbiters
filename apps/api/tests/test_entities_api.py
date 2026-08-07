from fastapi.testclient import TestClient


def _seed_pipeline(logged_in: TestClient) -> None:
    assert logged_in.post("/api/pipeline-stages/seed").status_code == 200


def test_full_customer_lifecycle_over_http(logged_in: TestClient) -> None:
    created = logged_in.post("/api/customers", json={"ragione_sociale": "ACME Srl"})
    assert created.status_code == 201
    customer_id = created.json()["id"]

    assert logged_in.get(f"/api/customers/{customer_id}").json()["ragione_sociale"] == "ACME Srl"

    updated = logged_in.patch(f"/api/customers/{customer_id}", json={"telefono": "0212345"})
    assert updated.json()["telefono"] == "0212345"

    assert logged_in.delete(f"/api/customers/{customer_id}").status_code == 204
    assert logged_in.get(f"/api/customers/{customer_id}").status_code == 404


def test_missing_customer_returns_a_problem_document(logged_in: TestClient) -> None:
    from uuid import uuid4

    response = logged_in.get(f"/api/customers/{uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"


def test_a_custom_field_defined_over_http_is_immediately_usable(logged_in: TestClient) -> None:
    """This is the whole point of dynamic fields: define it, then use it, with no deploy."""
    definition = logged_in.post(
        "/api/field-definitions",
        json={
            "entity_type": "customer",
            "key": "settore",
            "label": "Settore",
            "field_type": "select",
            "options": ["IT", "Retail"],
        },
    )
    assert definition.status_code == 201

    ok = logged_in.post(
        "/api/customers", json={"ragione_sociale": "Beta", "custom_fields": {"settore": "IT"}}
    )
    assert ok.status_code == 201
    assert ok.json()["custom_fields"] == {"settore": "IT"}

    bad = logged_in.post(
        "/api/customers", json={"ragione_sociale": "Gamma", "custom_fields": {"settore": "Altro"}}
    )
    assert bad.status_code == 422
    assert "IT" in bad.json()["expected"]


def test_schema_endpoint_describes_the_current_shape(logged_in: TestClient) -> None:
    logged_in.post(
        "/api/field-definitions",
        json={
            "entity_type": "customer",
            "key": "settore",
            "label": "Settore",
            "field_type": "text",
        },
    )
    body = logged_in.get("/api/schema/customer").json()

    assert body["entity_type"] == "customer"
    assert any(f["key"] == "settore" for f in body["custom_fields"])
    assert "ragione_sociale" in body["native_fields"]


def test_deal_lifecycle_including_the_kanban_move(logged_in: TestClient) -> None:
    _seed_pipeline(logged_in)
    stages = logged_in.get("/api/pipeline-stages").json()
    offerta = next(s for s in stages if s["nome"] == "Offerta")

    customer_id = logged_in.post("/api/customers", json={"ragione_sociale": "ACME"}).json()["id"]
    deal = logged_in.post(
        "/api/deals", json={"nome": "Progetto X", "customer_id": customer_id}
    ).json()

    moved = logged_in.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": offerta["id"]})
    assert moved.status_code == 200
    assert moved.json()["pipeline_stage_id"] == offerta["id"]


def test_timeline_endpoint_reports_what_happened(logged_in: TestClient) -> None:
    customer_id = logged_in.post("/api/customers", json={"ragione_sociale": "ACME"}).json()["id"]
    logged_in.patch(f"/api/customers/{customer_id}", json={"telefono": "02"})

    timeline = logged_in.get(f"/api/customers/{customer_id}/timeline").json()
    assert {entry["kind"] for entry in timeline} == {"created", "updated"}
    assert all(entry["actor_type"] == "user" for entry in timeline)


def test_timeline_endpoint_respects_a_bounded_limit(logged_in: TestClient) -> None:
    customer_id = logged_in.post("/api/customers", json={"ragione_sociale": "ACME"}).json()["id"]
    for index in range(5):
        logged_in.patch(f"/api/customers/{customer_id}", json={"telefono": f"0{index}"})

    limited = logged_in.get(f"/api/customers/{customer_id}/timeline", params={"limit": 2})
    assert len(limited.json()) == 2

    too_big = logged_in.get(f"/api/customers/{customer_id}/timeline", params={"limit": 201})
    assert too_big.status_code == 422


def test_deleting_a_customer_with_deals_is_409_and_says_how_many(logged_in: TestClient) -> None:
    _seed_pipeline(logged_in)
    customer_id = logged_in.post("/api/customers", json={"ragione_sociale": "ACME"}).json()["id"]
    logged_in.post("/api/deals", json={"nome": "X", "customer_id": customer_id})

    response = logged_in.delete(f"/api/customers/{customer_id}")
    assert response.status_code == 409
    assert response.json()["active_deals"] == 1


def test_list_supports_search_and_pagination(logged_in: TestClient) -> None:
    for index in range(3):
        logged_in.post("/api/customers", json={"ragione_sociale": f"Cliente {index}"})

    page = logged_in.get("/api/customers", params={"limit": 2}).json()
    assert len(page["items"]) == 2
    assert page["next_cursor"] is not None

    found = logged_in.get("/api/customers", params={"search": "Cliente 1"}).json()
    assert len(found["items"]) == 1


def test_a_pat_is_shown_once_and_then_only_by_prefix(logged_in: TestClient) -> None:
    created = logged_in.post("/api/tokens", json={"nome": "Claude"}).json()
    assert created["token"].startswith("pgc_")

    listed = logged_in.get("/api/tokens").json()
    assert listed[0]["prefix"] == created["token"][:12]
    assert all("token" not in entry for entry in listed)


def test_a_person_can_be_created_without_a_customer(logged_in: TestClient) -> None:
    response = logged_in.post("/api/people", json={"nome": "Mario"})
    assert response.status_code == 201
    assert response.json()["customer_id"] is None
