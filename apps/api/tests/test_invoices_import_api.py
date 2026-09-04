"""REST surface of the historical import (slice 9 §3.6)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

COLLABORATORE_PASSWORD = "supersegreta1"


def _second_actor(admin_client: TestClient, ruolo: str) -> TestClient:
    """A genuinely independent session, not `admin_client`'s own cookie jar.

    Copied from `test_invoices_api.py`: `logged_in` and `collaborator_client`
    (`apps/api/tests/conftest.py`) both build their `TestClient` from the same
    function-scoped `client` fixture, so requesting both in one test -- as this test
    would if it asked for `collaborator_client` alongside `customer` (which itself
    needs `logged_in`) -- leaves exactly one login active on that shared cookie jar,
    whichever fixture's own `/api/auth/login` call happened to resolve last. A fresh
    `TestClient(admin_client.app)` over the same ASGI app sidesteps that: same database
    session and storage overrides, independent cookie jar.
    """
    email = f"{ruolo}-{id(admin_client)}@pigro.it"
    created = admin_client.post(
        "/api/users",
        json={"email": email, "password": COLLABORATORE_PASSWORD, "nome": "Test", "ruolo": ruolo},
    )
    assert created.status_code == 201, created.text
    client = TestClient(admin_client.app, base_url="https://testserver")
    response = client.post(
        "/api/auth/login", json={"email": email, "password": COLLABORATORE_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def fiscal_profile(logged_in: TestClient) -> dict[str, Any]:
    response = logged_in.put("/api/fiscal-profile", json={"codice_regime": "RF19"})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def emitter(logged_in: TestClient) -> dict[str, Any]:
    response = logged_in.put(
        "/api/emitter",
        json={
            "ragione_sociale": "Humancraft di Ivan Sala",
            "partita_iva": "14518240966",
            "codice_fiscale": "HMCRFT00A01H501K",
            "indirizzo": "Via Vittorio Veneto 12",
            "cap": "20124",
            "comune": "Milano",
            "provincia": "MI",
            "nazione": "IT",
            "email": "someone@example.com",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def customer(logged_in: TestClient) -> dict[str, Any]:
    response = logged_in.post(
        "/api/customers",
        json={
            "ragione_sociale": "Acme S.r.l.",
            "partita_iva": "12345678901",
            "codice_sdi": "ABCDEFG",
            "indirizzo": "Corso Italia 5",
            "cap": "00100",
            "comune": "Roma",
            "provincia": "RM",
            "nazione": "IT",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _body(customer_id: str, numero: int, giorno: str) -> dict[str, Any]:
    return {
        "anno": 2026,
        "numero": numero,
        "data_emissione": giorno,
        "customer_id": customer_id,
        "causale": "207571/0426/Consulenza AI CTO Safely A2A",
        "righe": [
            {
                "descrizione": "207571/0426/Consulenza AI CTO Safely A2A",
                "quantita": "9",
                "prezzo_unitario": "380",
                "prezzo_totale": "3420.00",
                "aliquota_iva": "0",
                "natura": "N2.2",
            }
        ],
        "imponibile": "3420.00",
        "imposta": "0.00",
        "bollo": "2.00",
        "totale": "3422.00",
        "stato_pagamento": "incassato",
        "data_incasso": "2026-05-20",
    }


def test_an_admin_imports_and_sees_the_undeclared_gaps(
    logged_in: TestClient,
    customer: dict[str, Any],
    fiscal_profile: dict[str, Any],
    emitter: dict[str, Any],
) -> None:
    first = logged_in.post("/api/invoices/import", json=_body(customer["id"], 7, "2026-05-05"))
    assert first.status_code == 201, first.text
    assert first.json()["fattura"]["importata_da"] == "acme"
    assert first.json()["buchi_non_dichiarati"] == []

    second = logged_in.post("/api/invoices/import", json=_body(customer["id"], 9, "2026-06-05"))
    assert second.status_code == 201, second.text
    assert second.json()["buchi_non_dichiarati"] == [8]

    gaps = logged_in.post(
        "/api/invoices/register/2026/gaps", json={"buchi": [{"numero": 8, "motivo": "annullata"}]}
    )
    assert gaps.status_code == 200, gaps.text
    assert [g["numero"] for g in gaps.json()] == [8]
    assert logged_in.get("/api/invoices/register/2026/gaps").json()[0]["motivo"] == "annullata"

    # No artefact is produced by an import (the router's own docstring says so): the
    # XML the customer holds is the original, and this CRM never generated it, so
    # there is nothing behind `xml_document_id` to serve. That is a 404, not a 409 --
    # the same "not found, not a conflict" verdict `test_a_proforma_refuses_to_produce_xml`
    # (`test_invoices_api.py`) already accepts for a fattura with no XML yet. A 409
    # would only be right for a caller that asked this CRM to *produce* a fresh XML for
    # an imported row (`POST /{id}/artifacts` -> `export_xml`, covered at the service
    # layer by `packages/core/tests/test_invoice_import.py`); plain `GET .../xml` never
    # takes that path.
    xml = logged_in.get(f"/api/invoices/{first.json()['fattura']['id']}/xml")
    assert xml.status_code == 404, xml.text
    assert xml.json()["code"] == "not_found"


def test_a_collaborator_cannot_import(logged_in: TestClient, customer: dict[str, Any]) -> None:
    """`collaborator_client` is deliberately not used here: it shares its cookie jar
    with `logged_in`, and `customer` needs `logged_in` -- combining the two would leave
    whichever login resolves last active for the whole test (see `_second_actor`'s
    docstring above), so the request would silently run as the wrong actor instead of
    testing anything. `_second_actor` builds a truly independent session instead.
    """
    collaboratore = _second_actor(logged_in, "collaboratore")
    response = collaboratore.post(
        "/api/invoices/import", json=_body(customer["id"], 7, "2026-05-05")
    )
    assert response.status_code == 403, response.text
