"""The admin area over HTTP: a cookie in, the lists out, and nothing without it."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from orbiters_core.admin import AdminService
from orbiters_core.config import Settings

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"
CREDENTIALS = {"email": "ivan@orbiters.it", "password": "una-password-lunga"}


@pytest.fixture
def admin(api_engine: Engine, api_session: Session) -> Iterator[None]:
    settings = Settings(
        database_url=api_engine.url.render_as_string(hide_password=False),
        _env_file=None,  # type: ignore[call-arg]
    )
    AdminService(api_session, settings).create(
        CREDENTIALS["email"], "Ivan", CREDENTIALS["password"]
    )
    yield
    api_session.rollback()
    for table in ("comments", "admin_sessions", "admin_users", "freelancers", "companies"):
        api_session.execute(text(f"DELETE FROM {table}"))
    api_session.commit()


def _apply(client: TestClient, email: str = "ada@studio.it") -> None:
    response = client.post(
        "/api/hub/freelancers",
        data={
            "nome": "Ada",
            "cognome": "Lovelace",
            "email": email,
            "tariffa_giornaliera": "450",
            "posizione": "Backend developer",
            "remoto": "remoto",
        },
        files={"cv": ("Ada CV.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text


def test_without_the_cookie_every_admin_route_is_a_401(client: TestClient, admin: None) -> None:
    for path in (
        "/api/hub/auth/me",
        "/api/hub/freelancers",
        "/api/hub/companies",
        "/api/hub/signups",
    ):
        assert client.get(path).status_code == 401, path


def test_login_sets_a_secure_httponly_cookie_and_the_lists_open(
    client: TestClient, admin: None
) -> None:
    refused = client.post("/api/hub/auth/login", json={**CREDENTIALS, "password": "no"})
    assert refused.status_code == 401
    assert refused.json()["detail"] == "Credenziali non valide"

    login = client.post("/api/hub/auth/login", json=CREDENTIALS)
    assert login.status_code == 200, login.text
    assert login.json()["email"] == "ivan@orbiters.it"
    cookie = login.headers["set-cookie"].lower()
    assert "orbiters_admin=" in cookie and "httponly" in cookie and "secure" in cookie

    assert client.get("/api/hub/auth/me").json()["nome"] == "Ivan"
    _apply(client)
    listed = client.get("/api/hub/freelancers").json()
    assert listed["totale"] == 1
    item = listed["items"][0]
    assert item["cv_filename"] == "Ada CV.pdf" and "cv_bytes" not in item

    cv = client.get(f"/api/hub/freelancers/{item['id']}/cv")
    assert cv.status_code == 200
    assert cv.content == PDF
    assert cv.headers["content-type"].startswith("application/pdf")
    assert 'filename="Ada CV.pdf"' in cv.headers["content-disposition"]

    moved = client.patch(
        f"/api/hub/freelancers/{item['id']}", json={"stato": "contattato", "note": "ok"}
    )
    assert moved.status_code == 200 and moved.json()["stato"] == "contattato"
    wrong = client.patch(f"/api/hub/freelancers/{item['id']}", json={"stato": "forse"})
    assert wrong.status_code == 422
    assert wrong.json()["detail"][0]["loc"][-1] == "stato"
    missing = client.get("/api/hub/companies/00000000-0000-7000-8000-000000000000")
    assert missing.status_code == 404

    assert client.post("/api/hub/auth/logout").status_code == 204
    assert client.get("/api/hub/auth/me").status_code == 401


# ---- comments --------------------------------------------------------------------------

MISSING = "00000000-0000-7000-8000-000000000000"


def _login(client: TestClient) -> None:
    assert client.post("/api/hub/auth/login", json=CREDENTIALS).status_code == 200


def _request_company(client: TestClient) -> None:
    response = client.post(
        "/api/hub/companies",
        json={
            "nome_azienda": "ACME Srl",
            "referente": "Wile E.",
            "email": "wile@acme.it",
            "progetto": "Un backend developer per tre mesi.",
            "periodo_da": "2026-10-01",
            "durata": "3 mesi",
            "budget_giornaliero": "500",
        },
    )
    assert response.status_code == 201, response.text


def test_without_the_cookie_the_comment_routes_are_a_401(client: TestClient, admin: None) -> None:
    for kind in ("freelancers", "companies"):
        assert client.get(f"/api/hub/{kind}/{MISSING}/comments").status_code == 401
        assert (
            client.post(f"/api/hub/{kind}/{MISSING}/comments", json={"testo": "x"}).status_code
            == 401
        )


def test_a_comment_is_signed_by_the_logged_in_admin_and_read_newest_first(
    client: TestClient, admin: None
) -> None:
    _login(client)
    _apply(client)
    freelancer_id = client.get("/api/hub/freelancers").json()["items"][0]["id"]

    assert client.get(f"/api/hub/freelancers/{freelancer_id}/comments").json() == []
    first = client.post(
        f"/api/hub/freelancers/{freelancer_id}/comments",
        json={"testo": "  Sentito al telefono.\nRichiamare lunedì.  "},
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["testo"] == "Sentito al telefono.\nRichiamare lunedì."
    assert body["autore"] == "Ivan"
    assert body["entity_type"] == "freelancer" and body["entity_id"] == freelancer_id
    second = client.post(
        f"/api/hub/freelancers/{freelancer_id}/comments", json={"testo": "Ha mandato il portfolio."}
    )
    assert second.status_code == 201

    thread = client.get(f"/api/hub/freelancers/{freelancer_id}/comments").json()
    assert [c["id"] for c in thread] == [second.json()["id"], body["id"]]
    # The detail carries the same thread; the list does not.
    detail = client.get(f"/api/hub/freelancers/{freelancer_id}").json()
    assert [c["id"] for c in detail["commenti"]] == [second.json()["id"], body["id"]]
    assert detail["note"] is None
    assert client.get("/api/hub/freelancers").json()["items"][0]["commenti"] == []


def test_a_company_gets_its_own_thread(client: TestClient, admin: None) -> None:
    _login(client)
    _request_company(client)
    company_id = client.get("/api/hub/companies").json()["items"][0]["id"]
    posted = client.post(f"/api/hub/companies/{company_id}/comments", json={"testo": "Budget ok."})
    assert posted.status_code == 201, posted.text
    assert posted.json()["autore"] == "Ivan"
    assert [c["testo"] for c in client.get(f"/api/hub/companies/{company_id}/comments").json()] == [
        "Budget ok."
    ]
    assert [
        c["testo"] for c in client.get(f"/api/hub/companies/{company_id}").json()["commenti"]
    ] == ["Budget ok."]


def test_a_comment_on_a_missing_row_is_a_404_and_an_empty_one_a_422_naming_the_field(
    client: TestClient, admin: None
) -> None:
    _login(client)
    assert client.get(f"/api/hub/freelancers/{MISSING}/comments").status_code == 200
    missing = client.post(f"/api/hub/freelancers/{MISSING}/comments", json={"testo": "Nessuno."})
    assert missing.status_code == 404
    assert missing.json()["detail"] == f"freelancer {MISSING} non trovato"
    assert (
        client.post(f"/api/hub/companies/{MISSING}/comments", json={"testo": "x"}).status_code
        == 404
    )

    _apply(client)
    freelancer_id = client.get("/api/hub/freelancers").json()["items"][0]["id"]
    for testo in ("", "   ", "x" * 4001):
        refused = client.post(
            f"/api/hub/freelancers/{freelancer_id}/comments", json={"testo": testo}
        )
        assert refused.status_code == 422, testo[:10]
        assert refused.json()["detail"][0]["loc"][-1] == "testo"
    # The author is the session's, never the body's.
    forged = client.post(
        f"/api/hub/freelancers/{freelancer_id}/comments", json={"testo": "ok", "autore": "Altro"}
    )
    assert forged.status_code == 422
    assert client.get(f"/api/hub/freelancers/{freelancer_id}/comments").json() == []
