"""The member area over HTTP: a link in, a cookie out, and only your own row behind it."""

import logging
import re
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from orbiters_api.deps import get_sender
from orbiters_api.ratelimit import reset_rate_limit
from orbiters_core.admin import AdminService
from orbiters_core.config import Settings
from orbiters_core.mail import Mail, RecordingSender
from orbiters_core.perks import GUIDE_PATH

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"
ADMIN = {"email": "ivan@orbiters.it", "password": "una-password-lunga"}


class RefusingSender:
    """A sender the provider always turns away, for the test that a refusal is logged."""

    def send(self, mail: Mail) -> bool:
        return False


@pytest.fixture
def sender(client: TestClient) -> Iterator[RecordingSender]:
    recording = RecordingSender()
    client.app.dependency_overrides[get_sender] = lambda: recording  # type: ignore[attr-defined]
    yield recording


@pytest.fixture
def clean(api_session: Session) -> Iterator[None]:
    yield
    api_session.rollback()
    for table in (
        "member_sessions",
        "magic_link_tokens",
        "comments",
        "admin_sessions",
        "admin_users",
        "freelancers",
    ):
        api_session.execute(text(f"DELETE FROM {table}"))
    api_session.commit()


def _apply(client: TestClient, email: str, nome: str = "Ada") -> None:
    response = client.post(
        "/api/hub/freelancers",
        data={
            "nome": nome,
            "cognome": "Lovelace",
            "email": email,
            "tariffa_giornaliera": "450",
            "posizione": "Backend developer",
            "remoto": "remoto",
        },
        files={"cv": ("Ada CV.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text


def _enter(
    client: TestClient, sender: RecordingSender, email: str
) -> tuple[dict[str, object], httpx.Response]:
    assert client.post("/api/hub/auth/link", json={"email": email}).status_code == 202
    match = re.search(r"/entra\?t=([A-Za-z0-9_-]+)", sender.sent[-1].text)
    assert match
    entered = client.post("/api/hub/auth/enter", json={"token": match.group(1)})
    assert entered.status_code == 200, entered.text
    return entered.json(), entered


def test_without_a_sender_the_link_request_is_a_503_sentence(
    client: TestClient, clean: None
) -> None:
    client.app.dependency_overrides[get_sender] = lambda: None  # type: ignore[attr-defined]
    response = client.post("/api/hub/auth/link", json={"email": "ada@studio.it"})
    assert response.status_code == 503
    assert "non è ancora attivo" in response.json()["detail"]


def test_a_refused_mail_is_logged_without_the_address(
    client: TestClient, clean: None, caplog: pytest.LogCaptureFixture
) -> None:
    # `api_engine`'s `upgrade_to_head` runs Alembic's own `env.py`, whose `fileConfig`
    # disables every logger that already existed and is not in `alembic.ini`'s own
    # `[loggers]` list -- this module's among them. Undo that here so `caplog` can see
    # what this test is about; nothing at runtime relies on the logger being disabled.
    logging.getLogger("orbiters_api.routers.members").disabled = False
    client.app.dependency_overrides[get_sender] = lambda: RefusingSender()  # type: ignore[attr-defined]
    _apply(client, "ada@studio.it")
    with caplog.at_level(logging.WARNING):
        response = client.post("/api/hub/auth/link", json={"email": "ada@studio.it"})
    assert response.status_code == 202
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert any("refused by the provider" in record.getMessage() for record in warnings)
    assert "ada@studio.it" not in caplog.text


def test_the_link_request_answers_the_same_whether_the_address_applied_or_not(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    _apply(client, "ada@studio.it")
    known = client.post("/api/hub/auth/link", json={"email": "Ada@studio.it"})
    unknown = client.post("/api/hub/auth/link", json={"email": "nessuno@studio.it"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"ok": True}
    assert [mail.to for mail in sender.sent] == ["ada@studio.it"]
    assert "/entra?t=" in sender.sent[0].text


def test_the_link_enters_once_sets_the_member_cookie_and_opens_only_the_members_routes(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    _apply(client, "ada@studio.it")
    for path in ("/api/hub/me", "/api/hub/me/cv", "/api/hub/me/guida"):
        assert client.get(path).status_code == 401, path

    profile, entered = _enter(client, sender, "ada@studio.it")
    assert profile["email"] == "ada@studio.it"
    assert "stato" not in profile and "note" not in profile and "utm_source" not in profile
    cookie = client.cookies.get("orbiters_user")
    assert cookie
    set_cookie = entered.headers["set-cookie"].lower()
    assert "orbiters_user=" in set_cookie
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "max-age=2592000" in set_cookie  # settings.member_session_days * 86400, 30 days
    assert client.get("/api/hub/me").json()["nome"] == "Ada"

    # The same link a second time opens nothing.
    match = re.search(r"/entra\?t=([A-Za-z0-9_-]+)", sender.sent[-1].text)
    assert match
    again = client.post("/api/hub/auth/enter", json={"token": match.group(1)})
    assert again.status_code == 401
    assert again.json()["detail"].startswith("Link non valido o scaduto")

    # A member cookie is not an admin cookie.
    assert client.get("/api/hub/freelancers").status_code == 401
    assert client.get("/api/hub/auth/me").status_code == 401

    cv = client.get("/api/hub/me/cv")
    assert cv.status_code == 200 and cv.content == PDF
    assert 'filename="Ada CV.pdf"' in cv.headers["content-disposition"]

    logged_out = client.post("/api/hub/me/logout")
    assert logged_out.status_code == 204
    cleared = logged_out.headers["set-cookie"].lower()
    assert "orbiters_user=" in cleared
    assert 'orbiters_user=""' in cleared or "max-age=0" in cleared
    assert client.get("/api/hub/me").status_code == 401


def test_the_guide_is_a_perk_of_the_session_and_not_a_public_file(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    """The whole point of ORB-70's second half: the guide is behind the member session.

    Nothing about the file is asserted here beyond it being the one on disk, byte for
    byte, since `packages/core/tests/test_guide_pdf.py` owns what the PDF is. What this
    owns is who may have it: an anonymous caller gets the same 401 as `/me`, and a
    member gets the bytes as an attachment under the name they will see in their
    downloads folder.
    """
    _apply(client, "ada@studio.it")
    assert client.get("/api/hub/me/guida").status_code == 401

    _enter(client, sender, "ada@studio.it")
    answer = client.get("/api/hub/me/guida")
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/pdf"
    assert (
        answer.headers["content-disposition"]
        == 'attachment; filename="orbiters-guida-primi-passi-freelance.pdf"'
    )
    assert answer.content == GUIDE_PATH.read_bytes()

    client.post("/api/hub/me/logout")
    assert client.get("/api/hub/me/guida").status_code == 401


def test_a_wrong_token_is_a_401_and_a_malformed_one_a_422(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    assert client.post("/api/hub/auth/enter", json={"token": "a" * 43}).status_code == 401
    assert client.post("/api/hub/auth/enter", json={"token": "corto"}).status_code == 422


def test_replacing_the_cv_without_a_cookie_is_a_401_even_with_a_valid_pdf(
    client: TestClient, clean: None
) -> None:
    response = client.put("/api/hub/me/cv", files={"cv": ("cv.pdf", PDF, "application/pdf")})
    assert response.status_code == 401


def test_a_member_changes_their_answers_and_the_admin_sees_the_comment(
    client: TestClient, sender: RecordingSender, api_session: Session, clean: None
) -> None:
    _apply(client, "ada@studio.it")
    _enter(client, sender, "ada@studio.it")

    refused = client.patch(
        "/api/hub/me",
        json={
            "nome": "Ada",
            "cognome": "Lovelace",
            "linkedin_url": "http://linkedin.com/in/ada",
            "tariffa_giornaliera": "500",
            "posizione": "Backend developer",
            "remoto": "remoto",
            "links": [],
        },
    )
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"][-1] == "linkedin_url"

    changed = client.patch(
        "/api/hub/me",
        json={
            "nome": "Ada",
            "cognome": "Lovelace",
            "linkedin_url": None,
            "tariffa_giornaliera": "500",
            "posizione": "Staff engineer",
            "remoto": "ibrido",
            "links": ["https://github.com/ada"],
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["posizione"] == "Staff engineer"

    new_pdf = PDF + b"\n% v2\n"
    replaced = client.put(
        "/api/hub/me/cv", files={"cv": ("Ada 2026.pdf", new_pdf, "application/pdf")}
    )
    assert replaced.status_code == 200 and replaced.json()["cv_filename"] == "Ada 2026.pdf"
    not_a_pdf = client.put("/api/hub/me/cv", files={"cv": ("x.pdf", b"ciao", "application/pdf")})
    assert not_a_pdf.status_code == 422 and not_a_pdf.json()["detail"][0]["loc"][-1] == "cv"

    # `PUT /me/cv` now spends from the same public bucket as the wizard's routes
    # (the fix for the unbounded, unmetered upload); a fresh minute here keeps this
    # test about the admin's view of the thread, not about the rate limit's budget.
    reset_rate_limit()

    # The admin reads the thread the member wrote into.
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    AdminService(api_session, settings).create(ADMIN["email"], "Ivan", ADMIN["password"])
    # Log the member out first, so the client below holds only the admin cookie: an
    # admin session must not open the member routes any more than a member session
    # opens the admin ones.
    assert client.post("/api/hub/me/logout").status_code == 204
    assert client.post("/api/hub/auth/login", json=ADMIN).status_code == 200
    assert client.get("/api/hub/me").status_code == 401
    listed = client.get("/api/hub/freelancers").json()["items"]
    assert len(listed) == 1 and listed[0]["posizione"] == "Staff engineer"
    thread = client.get(f"/api/hub/freelancers/{listed[0]['id']}/comments").json()
    assert [comment["testo"] for comment in thread] == [
        "CV aggiornato dalla persona",
        "Profilo aggiornato dalla persona: tariffa giornaliera, posizione, modalità di lavoro, "
        "link",
    ]
    assert thread[0]["autore"] == "Ada Lovelace"


def test_a_member_never_sees_another_members_row(
    client: TestClient, sender: RecordingSender, clean: None
) -> None:
    _apply(client, "ada@studio.it", nome="Ada")
    _apply(client, "grace@studio.it", nome="Grace")
    assert _enter(client, sender, "grace@studio.it")[0]["nome"] == "Grace"
    assert client.get("/api/hub/me").json()["email"] == "grace@studio.it"
    # There is no route that takes an id: the only row reachable is the session's.
    assert client.get("/api/hub/me/00000000-0000-7000-8000-000000000000").status_code == 404


# ---- completing a card an admin wrote from a signup (ORB-155) -------------------------


def test_a_member_completes_the_card_an_admin_drafted(
    client: TestClient, sender: RecordingSender, clean: None, api_session: Session
) -> None:
    from orbiters_core.freelancers import FreelancerService
    from orbiters_core.schemas import FreelancerDraft, SignupCreate
    from orbiters_core.service import SignupService

    signup = SignupService(api_session).subscribe(
        SignupCreate(email="ada@studio.it", nome="Ada", cognome="Lovelace")
    )
    FreelancerService(api_session).draft_from_signup(
        signup.id,
        FreelancerDraft(nome="Ada", cognome="Lovelace", fonti=["https://ada.dev"]),
        "Claude",
    )
    profile, _ = _enter(client, sender, "ada@studio.it")
    assert profile["completa"] is False and profile["cv_filename"] is None
    assert client.get("/api/hub/me/cv").status_code == 404

    answered = client.patch(
        "/api/hub/me",
        json={
            "nome": "Ada",
            "cognome": "Lovelace",
            "linkedin_url": None,
            "tariffa_giornaliera": "500",
            "posizione": "CTO",
            "remoto": "ibrido",
            "links": [],
        },
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["completa"] is False
    with_cv = client.put("/api/hub/me/cv", files={"cv": ("Ada CV.pdf", PDF, "application/pdf")})
    assert with_cv.status_code == 200, with_cv.text
    assert with_cv.json()["completa"] is True
    assert client.get("/api/hub/me/cv").status_code == 200
    api_session.execute(text("DELETE FROM signups"))
    api_session.commit()
