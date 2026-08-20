from uuid import uuid4

from fastapi.testclient import TestClient


def _customer(client: TestClient) -> str:
    response = client.post("/api/customers", json={"ragione_sociale": "ACME S.r.l."})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_create_a_document_on_a_customer(logged_in: TestClient) -> None:
    customer_id = _customer(logged_in)
    response = logged_in.post(
        "/api/documents",
        json={"customer_id": customer_id, "tipo": "offerta", "titolo": "Offerta 1"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["stato"] == "bozza"


def test_a_document_with_neither_owner_is_a_422_problem_document(logged_in: TestClient) -> None:
    response = logged_in.post("/api/documents", json={"tipo": "documento", "titolo": "X"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "validation_failed"


def test_an_unknown_customer_is_a_404_problem_document(logged_in: TestClient) -> None:
    response = logged_in.post(
        "/api/documents",
        json={"customer_id": str(uuid4()), "tipo": "documento", "titolo": "X"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_list_filters_by_customer(logged_in: TestClient) -> None:
    customer_id = _customer(logged_in)
    logged_in.post(
        "/api/documents", json={"customer_id": customer_id, "tipo": "documento", "titolo": "A"}
    )
    response = logged_in.get("/api/documents", params={"customer_id": customer_id})
    assert response.status_code == 200
    assert [d["titolo"] for d in response.json()["items"]] == ["A"]


def test_a_limit_over_the_ceiling_is_refused(logged_in: TestClient) -> None:
    assert logged_in.get("/api/documents", params={"limit": 1000}).status_code == 422


def test_upload_a_version_and_download_it_back(logged_in: TestClient) -> None:
    customer_id = _customer(logged_in)
    document_id = logged_in.post(
        "/api/documents", json={"customer_id": customer_id, "tipo": "documento", "titolo": "Doc"}
    ).json()["id"]

    upload = logged_in.post(
        f"/api/documents/{document_id}/versions",
        files={"file": ("scansione.pdf", b"%PDF-1.7\nfinto\n", "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["numero"] == 1

    download = logged_in.get(f"/api/documents/{document_id}/download")
    assert download.status_code == 200
    assert download.content == b"%PDF-1.7\nfinto\n"
    assert download.headers["content-type"] == "application/pdf"
    assert "attachment" in download.headers["content-disposition"]


def test_an_unallowed_upload_type_is_refused(logged_in: TestClient) -> None:
    customer_id = _customer(logged_in)
    document_id = logged_in.post(
        "/api/documents", json={"customer_id": customer_id, "tipo": "documento", "titolo": "Doc"}
    ).json()["id"]
    response = logged_in.post(
        f"/api/documents/{document_id}/versions",
        files={"file": ("x.html", b"<script>alert(1)</script>", "text/html")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


def test_the_download_filename_cannot_inject_a_header(logged_in: TestClient) -> None:
    customer_id = _customer(logged_in)
    document_id = logged_in.post(
        "/api/documents",
        json={"customer_id": customer_id, "tipo": "documento", "titolo": 'a"\r\nX-Evil: 1'},
    ).json()["id"]
    logged_in.post(
        f"/api/documents/{document_id}/versions",
        files={"file": ("a.pdf", b"%PDF-1.7\n", "application/pdf")},
    )
    response = logged_in.get(f"/api/documents/{document_id}/download")
    assert response.status_code == 200
    assert "X-Evil" not in response.headers


def test_set_offer_state_and_refuse_an_undeclared_transition(logged_in: TestClient) -> None:
    customer_id = _customer(logged_in)
    document_id = logged_in.post(
        "/api/documents", json={"customer_id": customer_id, "tipo": "offerta", "titolo": "O"}
    ).json()["id"]
    assert (
        logged_in.post(f"/api/documents/{document_id}/stato", json={"stato": "inviata"}).json()[
            "stato"
        ]
        == "inviata"
    )
    conflict = logged_in.post(f"/api/documents/{document_id}/stato", json={"stato": "bozza"})
    assert conflict.status_code == 200  # inviata -> bozza is allowed
    # Now back in "bozza", whose only legal exit is "inviata": "accettata" is refused.
    forbidden = logged_in.post(f"/api/documents/{document_id}/stato", json={"stato": "accettata"})
    assert forbidden.status_code == 409
    assert forbidden.json()["code"] == "conflict"


def test_a_readonly_actor_cannot_create_a_document(readonly_client: TestClient) -> None:
    response = readonly_client.post(
        "/api/documents", json={"customer_id": str(uuid4()), "tipo": "documento", "titolo": "X"}
    )
    assert response.status_code == 403


def test_templates_crud_and_describe(logged_in: TestClient) -> None:
    created = logged_in.post(
        "/api/templates",
        json={
            "nome": "Consulenza CTO",
            "tipo": "offerta",
            "corpo_markdown": "Spett.le {{cliente.ragione_sociale}} — {{oggetto}}",
            "variabili_dichiarate": [
                {"nome": "oggetto", "etichetta": "Oggetto", "tipo": "text", "obbligatoria": True}
            ],
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    described = logged_in.get(f"/api/templates/{template_id}/describe")
    assert described.status_code == 200
    assert [v["nome"] for v in described.json()["variabili"]] == ["oggetto"]

    preview = logged_in.post(
        f"/api/templates/{template_id}/preview",
        json={"variabili": {"cliente": {"ragione_sociale": "ACME"}, "oggetto": "Advisory"}},
    )
    assert preview.status_code == 200
    assert preview.json()["markdown"] == "Spett.le ACME — Advisory"


def test_a_template_body_that_does_not_parse_is_a_422(logged_in: TestClient) -> None:
    response = logged_in.post(
        "/api/templates", json={"nome": "Rotto", "tipo": "offerta", "corpo_markdown": "{{#if x}}"}
    )
    assert response.status_code == 422
    assert "riga 1" in response.json()["reason"]


def test_a_template_can_be_deactivated_and_reactivated(logged_in: TestClient) -> None:
    created = logged_in.post(
        "/api/templates",
        json={"nome": "Da disattivare", "tipo": "offerta", "corpo_markdown": "Ciao"},
    )
    template_id = created.json()["id"]
    deactivated = logged_in.delete(f"/api/templates/{template_id}")
    assert deactivated.status_code == 200
    assert deactivated.json()["attivo"] is False
    reactivated = logged_in.post(f"/api/templates/{template_id}/activate")
    assert reactivated.status_code == 200
    assert reactivated.json()["attivo"] is True


def test_template_list_hides_inactive_ones_by_default(logged_in: TestClient) -> None:
    created = logged_in.post(
        "/api/templates",
        json={"nome": "Nascosto", "tipo": "offerta", "corpo_markdown": "Ciao"},
    )
    template_id = created.json()["id"]
    logged_in.delete(f"/api/templates/{template_id}")
    hidden = logged_in.get("/api/templates")
    assert template_id not in [t["id"] for t in hidden.json()["items"]]
    shown = logged_in.get("/api/templates", params={"include_inactive": True})
    assert template_id in [t["id"] for t in shown.json()["items"]]


def test_emitter_profile_is_404_before_it_is_saved_then_readable(logged_in: TestClient) -> None:
    assert logged_in.get("/api/emitter").status_code == 404
    saved = logged_in.put(
        "/api/emitter",
        json={"ragione_sociale": "Humancraft di Ivan Sala", "partita_iva": "14518240966"},
    )
    assert saved.status_code == 200, saved.text
    assert logged_in.get("/api/emitter").json()["partita_iva"] == "14518240966"


def test_a_non_admin_cannot_write_the_emitter_profile(collaborator_client: TestClient) -> None:
    response = collaborator_client.put("/api/emitter", json={"ragione_sociale": "X"})
    assert response.status_code == 403


def test_the_openapi_document_declares_the_new_routes(logged_in: TestClient) -> None:
    paths = logged_in.get("/openapi.json").json()["paths"]
    for path in (
        "/api/documents",
        "/api/documents/from-template",
        "/api/documents/{document_id}/download",
        "/api/templates/{template_id}/describe",
        "/api/emitter",
    ):
        assert path in paths, path
