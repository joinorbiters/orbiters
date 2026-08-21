"""Shapes only -- no session, no service. What is pinned here is the set of things
that reach Postgres if a schema forgets them: a width, a scale, a NUL byte, a bound.
"""

from datetime import date
from decimal import Decimal
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pigrocrm.core.documents.schemas import ALLOWED_CONTENT_TYPES, DocumentTipo
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.invoices.schemas import (
    ALLOWED_STATI,
    DESCRIZIONE_MAX_LENGTH,
    MAX_LINES,
    SNAPSHOT_VERSIONE,
    InvoiceCreate,
    InvoiceLineIn,
    InvoiceListQuery,
    InvoiceSnapshot,
    InvoiceUpdate,
    PartySnapshot,
)
from pigrocrm.core.schema_registry import CREATE_MODELS, ENTITY_TYPES, native_fields


def test_invoice_is_a_declared_entity_type_in_all_three_python_places() -> None:
    assert "invoice" in get_args(EntityType)
    assert "invoice" in ENTITY_TYPES
    assert CREATE_MODELS["invoice"] is InvoiceCreate


def test_native_fields_for_an_invoice_covers_the_derived_fiscal_columns() -> None:
    """`native_fields` derives from the Create schema, and an invoice's most
    collision-prone names -- `totale`, `imponibile`, `numero` -- are derived columns
    that no Create schema declares. A custom field labelled "Totale" slugifies to
    `totale`; A13 is still open, so nothing consults this list yet, but the list it
    will consult has to be right."""
    names = native_fields("invoice")
    assert {"customer_id", "tipo", "causale", "righe"} <= set(names)
    assert {"anno", "numero", "imponibile", "imposta", "bollo", "totale", "stato"} <= set(names)
    assert "custom_fields" not in names


def test_native_fields_for_the_older_entities_is_unchanged() -> None:
    """EXTRA_NATIVE_FIELDS is empty for them, so the derivation is still the whole
    answer and no existing behaviour moved."""
    assert native_fields("customer") == [
        name for name in CREATE_MODELS["customer"].model_fields if name != "custom_fields"
    ]


def test_documents_learns_the_three_invoice_artefact_types() -> None:
    assert {"fattura", "fattura_xml", "proforma"} <= set(get_args(DocumentTipo))
    assert ALLOWED_CONTENT_TYPES["application/xml"] == ".xml"


def test_the_state_machines_are_declared_per_tipo() -> None:
    """Two state machines in one column would be ambiguous, so the legal pairs are
    data here and a table constraint in the database."""
    assert {
        "fattura": frozenset({"bozza", "emessa", "annullata"}),
        "proforma": frozenset({"bozza", "confermata", "consumata"}),
    } == ALLOWED_STATI


def test_a_line_rejects_a_nul_byte_in_its_description() -> None:
    with pytest.raises(ValidationError):
        InvoiceLineIn(descrizione="Consulenza\x00", prezzo_unitario=Decimal("100.00"))


def test_a_line_description_is_bounded_to_the_column_width() -> None:
    with pytest.raises(ValidationError):
        InvoiceLineIn(
            descrizione="x" * (DESCRIZIONE_MAX_LENGTH + 1), prezzo_unitario=Decimal("100.00")
        )


def test_a_unit_price_keeps_six_decimals_and_refuses_a_seventh() -> None:
    """Numeric(12, 6): six decimals is what makes 33,3333 EUR/h expressible, and a
    seventh would be silently rounded by Postgres while the response still reported
    the original."""
    assert InvoiceLineIn(
        descrizione="Consulenza", prezzo_unitario=Decimal("33.333333")
    ).prezzo_unitario == Decimal("33.333333")
    with pytest.raises(ValidationError):
        InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("33.3333331"))


def test_a_unit_price_beyond_twelve_digits_is_refused_before_postgres_sees_it() -> None:
    with pytest.raises(ValidationError):
        InvoiceLineIn(descrizione="Consulenza", prezzo_unitario=Decimal("1234567.000000"))


def test_a_line_never_carries_its_own_natura() -> None:
    """`natura` and `riferimento_normativo` are the regime's answer, not the caller's:
    accepting them would make the table constraint
    `(aliquota_iva = 0) = (natura IS NOT NULL)` reachable from a request body."""
    assert "natura" not in InvoiceLineIn.model_fields
    assert "riferimento_normativo" not in InvoiceLineIn.model_fields
    with pytest.raises(ValidationError):
        InvoiceLineIn(descrizione="x", prezzo_unitario=Decimal("1.00"), natura="N2.2")


def test_an_invoice_cannot_be_created_with_more_lines_than_the_bound() -> None:
    line = {"descrizione": "x", "prezzo_unitario": "1.00"}
    with pytest.raises(ValidationError):
        InvoiceCreate(customer_id=uuid4(), righe=[line] * (MAX_LINES + 1))


def test_update_exposes_only_text_columns_and_custom_fields() -> None:
    """A14 is sidestepped rather than reproduced: every native column on this schema
    is text-shaped, so `""` is a real "clear it" spelling. No typed column -- numeric,
    date or literal -- appears here, which is what removes the A14 shape from this
    surface instead of hitting it again. `causale` is editable but only while the
    invoice is a draft, which the service enforces with `ImmutableField`."""
    assert set(InvoiceUpdate.model_fields) == {"causale", "note_interne", "custom_fields"}


def test_the_list_query_limit_is_bounded_in_the_schema_not_only_the_router() -> None:
    assert InvoiceListQuery().limit == 50
    with pytest.raises(ValidationError):
        InvoiceListQuery(limit=201)


def test_a_snapshot_round_trips_through_json_with_its_version() -> None:
    party = PartySnapshot(
        ragione_sociale="Rossi & C.",
        partita_iva="12345678901",
        codice_fiscale=None,
        codice_sdi="ABCDEFG",
        pec=None,
        indirizzo="Via Roma 1",
        cap="20100",
        comune="Milano",
        provincia="MI",
        nazione="IT",
        email=None,
        telefono=None,
        sito_web=None,
    )
    snapshot = InvoiceSnapshot(
        versione=SNAPSHOT_VERSIONE,
        emittente=party,
        cliente=party,
        fiscale={
            "codice_regime": "RF19",
            "aliquota_iva_default": Decimal("0.00"),
            "natura_default": "N2.2",
            "riferimento_normativo": "art. 1",
            "applica_bollo": True,
            "soglia_bollo": Decimal("77.47"),
            "importo_bollo": Decimal("2.00"),
            "condizioni_pagamento": "TP02",
            "modalita_pagamento": "MP05",
            "giorni_scadenza": 30,
            "iban": None,
        },
    )
    payload = snapshot.model_dump(mode="json")
    assert payload["versione"] == 1
    restored = InvoiceSnapshot.model_validate(payload)
    assert restored == snapshot


def test_an_unversioned_snapshot_payload_is_refused() -> None:
    """A JSON blob written today is read by code three years from now; a payload with
    no version is interpreted by guessing. That is what the column costs and what it
    buys."""
    with pytest.raises(ValidationError):
        InvoiceSnapshot.model_validate({"emittente": {}, "cliente": {}, "fiscale": {}})


def test_an_issue_request_may_carry_a_date_and_nothing_else() -> None:
    from pigrocrm.core.invoices.schemas import InvoiceIssue

    assert set(InvoiceIssue.model_fields) == {"data_emissione"}
    assert InvoiceIssue(data_emissione=date(2026, 8, 20)).data_emissione == date(2026, 8, 20)
    assert InvoiceIssue().data_emissione is None
