"""The admin area over HTTP: a cookie in, the lists out, and nothing without it."""

import json
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from orbiters_api.deps import get_http_call
from orbiters_core.admin import AdminService
from orbiters_core.config import Settings, get_settings
from orbiters_core.perks import PerkService

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
    for table in (
        "guide_downloads",
        "comments",
        "admin_sessions",
        "admin_users",
        "freelancers",
        "companies",
        "signups",
    ):
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
        "/api/hub/admins",
        "/api/hub/pigro/istanze",
        "/api/hub/perks/guida",
    ):
        assert client.get(path).status_code == 401, path
    refused = client.post(
        "/api/hub/admins",
        json={"email": "x@orbiters.it", "nome": "X", "password": "una-password-lunga"},
    )
    assert refused.status_code == 401
    assert client.patch(f"/api/hub/admins/{MISSING}", json={"nome": "X"}).status_code == 401


def test_the_guide_page_counts_downloads_and_names_who_took_it(
    client: TestClient, admin: None, api_session: Session
) -> None:
    """ORB-156: zero of everything on an empty hub, then the numbers follow the rows.
    Two people on file, three downloads by one of them: totale 3, membri 1 of 2, all
    three in the last week, the latest first, each with the member's name."""
    assert client.post("/api/hub/auth/login", json=CREDENTIALS).status_code == 200
    empty = client.get("/api/hub/perks/guida")
    assert empty.status_code == 200
    assert empty.json() == {
        "totale": 0,
        "membri": 0,
        "membri_totali": 0,
        "ultimi_7_giorni": 0,
        "recenti": [],
    }

    _apply(client, "ada@studio.it")
    _apply(client, "bob@studio.it")
    listed = client.get("/api/hub/freelancers").json()["items"]
    people = {item["email"]: item["id"] for item in listed}
    perks = PerkService(api_session)
    for _ in range(3):
        perks.record_guide_download(UUID(people["ada@studio.it"]))

    stats = client.get("/api/hub/perks/guida").json()
    assert (stats["totale"], stats["membri"], stats["membri_totali"]) == (3, 1, 2)
    assert stats["ultimi_7_giorni"] == 3
    assert len(stats["recenti"]) == 3
    latest = stats["recenti"][0]
    assert (latest["nome"], latest["cognome"]) == ("Ada", "Lovelace")
    assert latest["email"] == "ada@studio.it"
    assert latest["freelancer_id"] == people["ada@studio.it"]
    moments = [item["downloaded_at"] for item in stats["recenti"]]
    assert moments == sorted(moments, reverse=True)


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


# ---- admins ----------------------------------------------------------------------------
#
# ORB-123: an admin creates the next one from the area, with the CLI's own rules, and the
# list says who is there. No deactivation and no deletion here, on purpose.


def test_an_admin_lists_the_admins_and_creates_one_who_can_then_log_in(
    client: TestClient, admin: None
) -> None:
    _login(client)
    before = client.get("/api/hub/admins")
    assert before.status_code == 200
    assert [row["email"] for row in before.json()] == ["ivan@orbiters.it"]
    assert before.json()[0]["attivo"] is True and "created_at" in before.json()[0]
    assert "password_hash" not in before.json()[0]

    created = client.post(
        "/api/hub/admins",
        json={
            "email": "Lorenzo@Orbiters.it",
            "nome": " Lorenzo ",
            "password": "una-password-lunga",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["email"] == "lorenzo@orbiters.it"
    assert created.json()["nome"] == "Lorenzo"
    assert "password" not in created.text and "password_hash" not in created.text

    after = client.get("/api/hub/admins").json()
    assert [row["email"] for row in after] == ["ivan@orbiters.it", "lorenzo@orbiters.it"]

    # The new admin's credentials open a session of their own.
    assert client.post("/api/hub/auth/logout").status_code == 204
    login = client.post(
        "/api/hub/auth/login",
        json={"email": "lorenzo@orbiters.it", "password": "una-password-lunga"},
    )
    assert login.status_code == 200 and login.json()["nome"] == "Lorenzo"


def test_creating_an_admin_points_the_form_at_the_field_that_is_wrong(
    client: TestClient, admin: None
) -> None:
    _login(client)
    duplicate = client.post(
        "/api/hub/admins",
        json={"email": "IVAN@orbiters.it", "nome": "Ancora", "password": "una-password-lunga"},
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"][0]["loc"][-1] == "email"
    short = client.post(
        "/api/hub/admins", json={"email": "corta@orbiters.it", "nome": "Corta", "password": "breve"}
    )
    assert short.status_code == 422
    assert short.json()["detail"][0]["loc"][-1] == "password"
    malformed = client.post(
        "/api/hub/admins",
        json={"email": "non-una-mail", "nome": "X", "password": "una-password-lunga"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"][0]["loc"][-1] == "email"
    for nome in ("   ", "x" * 121, "Ada\x00"):
        bad_name = client.post(
            "/api/hub/admins",
            json={"email": "nome@orbiters.it", "nome": nome, "password": "una-password-lunga"},
        )
        assert bad_name.status_code == 422, nome
        assert bad_name.json()["detail"][0]["loc"][-1] == "nome"
    # A key the schema does not declare is refused, not silently dropped: nobody creates
    # an admin with `attivo` chosen from outside.
    extra = client.post(
        "/api/hub/admins",
        json={
            "email": "extra@orbiters.it",
            "nome": "Extra",
            "password": "una-password-lunga",
            "attivo": False,
        },
    )
    assert extra.status_code == 422
    assert [row["email"] for row in client.get("/api/hub/admins").json()] == ["ivan@orbiters.it"]


def test_an_admin_changes_another_admins_name_address_or_password(
    client: TestClient, admin: None
) -> None:
    # ORB-129. The password field is optional and means «keep it» when absent.
    _login(client)
    created = client.post(
        "/api/hub/admins",
        json={"email": "lorenzo@orbiters.it", "nome": "Lorenzo", "password": "una-password-lunga"},
    ).json()

    renamed = client.patch(f"/api/hub/admins/{created['id']}", json={"nome": " Lorenzo Fiore "})
    assert renamed.status_code == 200, renamed.text
    assert (
        renamed.json()["nome"] == "Lorenzo Fiore"
        and renamed.json()["email"] == "lorenzo@orbiters.it"
    )
    assert "password" not in renamed.text

    moved = client.patch(
        f"/api/hub/admins/{created['id']}",
        json={"email": "Lorenzo.Fiore@Orbiters.it", "password": "nuova-password-lunga"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["email"] == "lorenzo.fiore@orbiters.it"
    listed = client.get("/api/hub/admins").json()
    assert [row["email"] for row in listed] == ["ivan@orbiters.it", "lorenzo.fiore@orbiters.it"]

    # The new credentials open a session; the old password does not.
    assert client.post("/api/hub/auth/logout").status_code == 204
    old = client.post(
        "/api/hub/auth/login",
        json={"email": "lorenzo.fiore@orbiters.it", "password": "una-password-lunga"},
    )
    assert old.status_code == 401
    new = client.post(
        "/api/hub/auth/login",
        json={"email": "lorenzo.fiore@orbiters.it", "password": "nuova-password-lunga"},
    )
    assert new.status_code == 200 and new.json()["nome"] == "Lorenzo Fiore"


def test_changing_an_admin_points_the_form_at_the_field_that_is_wrong(
    client: TestClient, admin: None
) -> None:
    _login(client)
    me = client.get("/api/hub/auth/me").json()
    other = client.post(
        "/api/hub/admins",
        json={"email": "lorenzo@orbiters.it", "nome": "Lorenzo", "password": "una-password-lunga"},
    ).json()
    for body, field in (
        ({"email": "IVAN@orbiters.it"}, "email"),
        ({"email": "non-una-mail"}, "email"),
        ({"nome": "   "}, "nome"),
        ({"nome": "x" * 121}, "nome"),
        ({"password": "breve"}, "password"),
        ({"attivo": False}, "attivo"),
    ):
        refused = client.patch(f"/api/hub/admins/{other['id']}", json=body)
        assert refused.status_code == 422, body
        assert refused.json()["detail"][0]["loc"][-1] == field, body
    # An empty password in the body is «keep it», not a five-character password.
    kept = client.patch(f"/api/hub/admins/{other['id']}", json={"password": ""})
    assert kept.status_code == 200
    # One's own row is editable like any other; the same address on itself is no duplicate.
    own = client.patch(
        f"/api/hub/admins/{me['id']}", json={"email": "IVAN@orbiters.it", "nome": "Ivan S."}
    )
    assert own.status_code == 200 and own.json()["nome"] == "Ivan S."
    assert client.get("/api/hub/auth/me").json()["nome"] == "Ivan S."
    assert client.patch(f"/api/hub/admins/{MISSING}", json={"nome": "Nessuno"}).status_code == 404


def test_a_new_password_logs_the_other_admin_out_and_keeps_me_in(
    client: TestClient, admin: None
) -> None:
    _login(client)
    other = client.post(
        "/api/hub/admins",
        json={"email": "lorenzo@orbiters.it", "nome": "Lorenzo", "password": "una-password-lunga"},
    ).json()
    # Lorenzo logs in from his own browser.
    lorenzo = TestClient(client.app, base_url="https://testserver")
    assert (
        lorenzo.post(
            "/api/hub/auth/login",
            json={"email": "lorenzo@orbiters.it", "password": "una-password-lunga"},
        ).status_code
        == 200
    )
    assert lorenzo.get("/api/hub/auth/me").status_code == 200

    # I change his password: his session is gone, mine is untouched.
    changed = client.patch(
        f"/api/hub/admins/{other['id']}", json={"password": "nuova-password-lunga"}
    )
    assert changed.status_code == 200
    assert lorenzo.get("/api/hub/auth/me").status_code == 401
    assert client.get("/api/hub/auth/me").status_code == 200

    # I change my own: I am still in.
    me = client.get("/api/hub/auth/me").json()
    own = client.patch(f"/api/hub/admins/{me['id']}", json={"password": "anche-la-mia-nuova"})
    assert own.status_code == 200
    assert client.get("/api/hub/auth/me").status_code == 200


# ---- the spaces of PigroCRM (ORB-142) --------------------------------------------------
#
# The hub never touches the CRM's database: it asks the CRM's API with a token, through
# the same HTTP seam the mail and the pixel use, so these tests hand a fake and read what
# would have left.

PIGRO_TOKEN = "un-token-lungo-solo-per-questa-suite"
PIGRO_ROWS = [
    {
        "id": "0192c6f0-0000-7000-8000-000000000002",
        "slug": "studio-ada",
        "owner_email": "ada@studio.it",
        "created_at": "2026-09-10T09:00:00Z",
    },
    {
        "id": "0192c6f0-0000-7000-8000-000000000001",
        "slug": "bob-dev",
        "owner_email": "Bob@Example.org",
        "created_at": "2026-09-09T09:00:00Z",
    },
]


class FakePigro:
    """Answers what a test tells it to and keeps every call it received."""

    def __init__(self, status: int = 200, body: object = None) -> None:
        self.status = status
        self.body = json.dumps(PIGRO_ROWS if body is None else body).encode()
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.raises: Exception | None = None

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, headers))
        if self.raises is not None:
            raise self.raises
        return self.status, self.body


@pytest.fixture
def pigro(client: TestClient) -> Iterator[FakePigro]:
    fake = FakePigro()
    client.app.dependency_overrides[get_http_call] = lambda: fake  # type: ignore[attr-defined]
    # Both values declared, so a developer's shell exporting `ORBITERS_PIGRO_API_URL`
    # cannot change what the assertion below expects.
    client.app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[attr-defined]
        pigro_api_url="https://pigro.joinorbiters.com",
        pigro_registry_token=PIGRO_TOKEN,
        _env_file=None,  # type: ignore[call-arg]
    )
    yield fake


def test_without_a_pigro_token_the_spaces_are_a_503_sentence(
    client: TestClient, admin: None
) -> None:
    _login(client)
    response = client.get("/api/hub/pigro/istanze")
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == (
        "Il registro di Pigro non è configurato: manca ORBITERS_PIGRO_REGISTRY_TOKEN."
    )


def test_the_spaces_come_from_the_crm_with_the_token_and_name_the_member_who_owns_one(
    client: TestClient, admin: None, pigro: FakePigro
) -> None:
    _login(client)
    _apply(client, email="ada@studio.it")
    response = client.get("/api/hub/pigro/istanze")
    assert response.status_code == 200, response.text

    # One GET to the CRM, the token as a bearer, and nothing else in the request.
    assert [(method, url) for method, url, _ in pigro.calls] == [
        ("GET", "https://pigro.joinorbiters.com/api/tenants/")
    ]
    assert pigro.calls[0][2]["Authorization"] == f"Bearer {PIGRO_TOKEN}"

    body = response.json()
    assert body["totale"] == 2
    ada, bob = body["items"]
    assert ada["slug"] == "studio-ada"
    assert ada["url"] == "https://pigro.joinorbiters.com/studio-ada/app/"
    assert ada["owner_email"] == "ada@studio.it"
    assert ada["created_at"].startswith("2026-09-10")
    # Ada filled in the wizard, so her space names her and points at her card.
    assert ada["membro"]["nome"] == "Ada"
    assert ada["membro"]["cognome"] == "Lovelace"
    freelancer_id = ada["membro"]["id"]
    assert client.get(f"/api/hub/freelancers/{freelancer_id}").json()["email"] == "ada@studio.it"
    # Bob never did: the address is all the hub knows, as the CRM wrote it.
    assert bob["slug"] == "bob-dev"
    assert bob["membro"] is None


def test_a_member_is_matched_whatever_the_case_of_the_address(
    client: TestClient, admin: None, pigro: FakePigro
) -> None:
    _login(client)
    _apply(client, email="bob@example.org")
    items = client.get("/api/hub/pigro/istanze").json()["items"]
    assert items[1]["owner_email"] == "Bob@Example.org"
    assert items[1]["membro"]["nome"] == "Ada"


def test_when_the_crm_refuses_or_falls_over_the_answer_is_a_502_sentence(
    client: TestClient, admin: None, pigro: FakePigro
) -> None:
    _login(client)
    pigro.status = 401
    pigro.body = b'{"detail":"token non valido"}'
    refused = client.get("/api/hub/pigro/istanze")
    assert refused.status_code == 502, refused.text
    assert refused.json()["detail"] == "Pigro non ha risposto (401)."
    pigro.status = 200
    pigro.body = b"<html>not json</html>"
    garbled = client.get("/api/hub/pigro/istanze")
    assert garbled.status_code == 502, garbled.text
    assert garbled.json()["detail"] == "Pigro ha risposto qualcosa che non è un elenco."
    # A refused connection, a DNS miss or a timeout: the seam raises, and that is the most
    # likely failure of all, so it too is a 502 sentence rather than a traceback.
    pigro.raises = OSError("connection refused")
    down = client.get("/api/hub/pigro/istanze")
    assert down.status_code == 502, down.text
    assert down.json()["detail"] == "Pigro non risponde."


# ---- a card from a signup (ORB-155) --------------------------------------------------


def _signup(client: TestClient, email: str = "ada@studio.it") -> str:
    response = client.post(
        "/api/orbiters/signups", json={"email": email, "nome": "Ada", "cognome": "Lovelace"}
    )
    assert response.status_code in (200, 201), response.text
    _login(client)
    listed = client.get("/api/hub/signups").json()["iscrizioni"]
    return next(item["id"] for item in listed if item["email"] == email)


DRAFT = {
    "nome": "Ada",
    "cognome": "Lovelace",
    "linkedin_url": "https://www.linkedin.com/in/ada",
    "posizione": "Backend developer",
    "links": ["https://github.com/ada"],
    "fonti": ["https://www.linkedin.com/in/ada"],
}


def test_without_the_cookie_the_card_from_a_signup_is_a_401(
    client: TestClient, admin: None
) -> None:
    response = client.post(f"/api/hub/signups/{MISSING}/scheda", json=DRAFT)
    assert response.status_code == 401


def test_an_admin_writes_an_incomplete_card_from_a_signup_and_the_list_points_at_it(
    client: TestClient, admin: None
) -> None:
    signup_id = _signup(client)
    created = client.post(f"/api/hub/signups/{signup_id}/scheda", json=DRAFT)
    assert created.status_code == 201, created.text
    card = created.json()
    assert card["email"] == "ada@studio.it"
    assert card["compilata_da"] == "admin" and card["completa"] is False
    assert card["cv_filename"] is None and card["tariffa_giornaliera"] is None
    assert card["commenti"][0]["autore"] == "Ivan"
    assert "https://www.linkedin.com/in/ada" in card["commenti"][0]["testo"]

    items = client.get("/api/hub/signups").json()["iscrizioni"]
    item = next(i for i in items if i["id"] == signup_id)
    assert item["freelancer_id"] == card["id"]
    assert client.get(f"/api/hub/freelancers/{card['id']}/cv").status_code == 404
    listed = client.get("/api/hub/freelancers").json()["items"]
    assert listed[0]["id"] == card["id"] and listed[0]["completa"] is False

    # A wrong id is a 404, a bad body a 422 naming the field, as everywhere else.
    assert client.post(f"/api/hub/signups/{MISSING}/scheda", json=DRAFT).status_code == 404
    bad = client.post(f"/api/hub/signups/{signup_id}/scheda", json={**DRAFT, "fonti": []})
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["loc"][-1] == "fonti"


def test_research_is_refused_on_a_card_the_person_filled(client: TestClient, admin: None) -> None:
    _apply(client)
    signup_id = _signup(client)
    body = {**DRAFT, "posizione": "CTO"}
    refused = client.post(f"/api/hub/signups/{signup_id}/scheda", json=body)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"][0]["loc"][-1] == "email"
    assert client.get("/api/hub/freelancers").json()["items"][0]["posizione"] == "Backend developer"
