"""The hub's two public writes: multipart with a CV, and JSON. Both mute, both limited."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from orbiters_api.ratelimit import SIGNUPS_PER_MINUTE

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"


def _form(**overrides: str) -> dict[str, str]:
    form = {
        "nome": "Ada",
        "cognome": "Lovelace",
        "email": "ada@studio.it",
        "tariffa_giornaliera": "450,00",
        "posizione": "Backend developer",
        "remoto": "remoto",
        "utm_source": "linkedin",
    }
    form.update(overrides)
    return form


def _clean(session: Session) -> None:
    session.execute(text("DELETE FROM freelancers"))
    session.execute(text("DELETE FROM companies"))
    session.commit()


def test_an_application_with_a_cv_is_accepted_and_stored(
    client: TestClient, api_session: Session
) -> None:
    _clean(api_session)
    response = client.post(
        "/api/hub/freelancers",
        data={**_form(), "links": ["https://github.com/ada", "https://ada.dev/"]},
        files={"cv": ("Ada CV.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    assert response.json() == {"ok": True}
    row = api_session.execute(
        text(
            "SELECT email, tariffa_giornaliera, cv_filename, cv_size, links, utm_source "
            "FROM freelancers"
        )
    ).one()
    assert row.email == "ada@studio.it"
    # The Italian comma is accepted and the value is the number, to the cent.
    assert str(row.tariffa_giornaliera) == "450.00"
    assert (row.cv_filename, row.cv_size) == ("Ada CV.pdf", len(PDF))
    assert row.links == ["https://github.com/ada", "https://ada.dev/"]
    assert row.utm_source == "linkedin"


def test_the_page_the_person_started_from_is_stored_beside_the_campaign(
    client: TestClient, api_session: Session
) -> None:
    """ORB-167: `origine` is the page of the site the door was on, `home` or `pigrocrm`,
    as the landing's script put it on the link. A slug, or nothing: a value that is not
    one is refused with the field's name, the same as any other field."""
    _clean(api_session)
    accepted = client.post(
        "/api/hub/freelancers",
        data={**_form(), "origine": "pigrocrm"},
        files={"cv": ("Ada CV.pdf", PDF, "application/pdf")},
    )
    assert accepted.status_code == 201, accepted.text
    row = api_session.execute(text("SELECT origine, utm_source FROM freelancers")).one()
    assert (row.origine, row.utm_source) == ("pigrocrm", "linkedin")

    refused = client.post(
        "/api/hub/freelancers",
        data={**_form(email="bob@studio.it"), "origine": "<script>"},
        files={"cv": ("CV.pdf", PDF, "application/pdf")},
    )
    assert refused.status_code == 422
    assert "origine" in [error["loc"][-1] for error in refused.json()["detail"]]

    company = client.post(
        "/api/hub/companies",
        json={
            "nome_azienda": "XYZ",
            "referente": "Grace Hopper",
            "email": "grace@xyz.it",
            "progetto": "Un backend da rifare.",
            "periodo_da": "2026-10-01",
            "durata": "3 mesi",
            "budget_giornaliero": "500",
            "utm": {"utm_source": "linkedin", "origine": "home"},
        },
    )
    assert company.status_code == 201, company.text
    assert api_session.execute(text("SELECT origine FROM companies")).scalar() == "home"


def test_a_missing_or_non_pdf_cv_is_a_422_that_names_the_field(
    client: TestClient, api_session: Session
) -> None:
    _clean(api_session)
    response = client.post(
        "/api/hub/freelancers", data=_form(), files={"cv": ("cv.pdf", b"nope", "application/pdf")}
    )
    assert response.status_code == 422
    assert {error["loc"][-1] for error in response.json()["detail"]} == {"cv"}
    assert api_session.execute(text("SELECT count(*) FROM freelancers")).scalar() == 0


def test_a_field_the_form_refuses_is_a_422_in_the_same_shape_as_a_json_body(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/hub/freelancers",
        data=_form(remoto="quando capita", tariffa_giornaliera="tanto"),
        files={"cv": ("cv.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 422
    fields = {error["loc"][-1] for error in response.json()["detail"]}
    # The number is checked first, on its own, because it is parsed by hand.
    assert fields == {"tariffa_giornaliera"}


def test_a_company_request_is_accepted_and_the_answer_says_nothing_else(
    client: TestClient, api_session: Session
) -> None:
    _clean(api_session)
    response = client.post(
        "/api/hub/companies",
        json={
            "nome_azienda": "ACME Srl",
            "referente": "Wile E.",
            "email": "wile@acme.it",
            "progetto": "Serve un backend developer per tre mesi.",
            "periodo_da": "2026-10-01",
            "durata": "3 mesi",
            "budget_giornaliero": "500",
            "utm": {"utm_source": "google"},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json() == {"ok": True}
    row = api_session.execute(
        text("SELECT nome_azienda, periodo_da, utm_source FROM companies")
    ).one()
    assert (row.nome_azienda, str(row.periodo_da), row.utm_source) == (
        "ACME Srl",
        "2026-10-01",
        "google",
    )


def test_the_three_public_writes_share_one_budget_per_client(
    client: TestClient, api_session: Session
) -> None:
    _clean(api_session)
    body = {
        "nome_azienda": "ACME Srl",
        "referente": "Wile E.",
        "email": "wile@acme.it",
        "progetto": "Un progetto",
        "periodo_da": "2026-10-01",
        "durata": "3 mesi",
        "budget_giornaliero": "500",
    }
    for _ in range(SIGNUPS_PER_MINUTE - 1):
        assert client.post("/api/hub/companies", json=body).status_code == 201
    assert (
        client.post(
            "/api/orbiters/signups", json={"email": "ada@studio.it", "nome": "Ada", "cognome": "L"}
        ).status_code
        == 201
    )
    refused = client.post("/api/hub/companies", json=body)
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "60"
