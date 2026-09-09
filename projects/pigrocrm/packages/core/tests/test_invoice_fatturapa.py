"""The generator, proven against the official schema and against a hostile value.

No database, no session, no container: the exporter reads an `InvoiceForExport` and
returns bytes, which is exactly what makes these cases cheap enough to be exhaustive.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fpr12 import assert_valid
from lxml import etree

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.invoices.fatturapa import (
    _INDIRIZZO_MAX,
    FatturaPAExporter,
    check_party_exportable,
    normalise_fiscal_id,
)
from pigrocrm.core.invoices.schemas import (
    SNAPSHOT_VERSIONE,
    InvoiceForExport,
    InvoiceLineRead,
    InvoiceSnapshot,
    PartySnapshot,
)
from pigrocrm.core.invoices.totals import ComputedLine, build_riepilogo, sum_totals

EMITTENTE = PartySnapshot(
    ragione_sociale="Humancraft di Ivan Sala",
    partita_iva="14518240966",
    codice_fiscale="HMCRFT00A01H501K",
    codice_sdi=None,
    pec="someone@example.com",
    indirizzo="Via Vittorio Veneto 12",
    cap="20124",
    comune="Milano",
    provincia="MI",
    nazione="IT",
    email="someone@example.com",
    telefono="+39 02 1234567",
    sito_web="https://humancraft.tech",
)

FISCALE = {
    "codice_regime": "RF19",
    "aliquota_iva_default": Decimal("0.00"),
    "natura_default": "N2.2",
    "riferimento_normativo": (
        "Operazione non soggetta a IVA ai sensi dell'art. 1, commi 54-89, "
        "L. 190/2014 - regime forfettario"
    ),
    "applica_bollo": True,
    "soglia_bollo": Decimal("77.47"),
    "importo_bollo": Decimal("2.00"),
    "condizioni_pagamento": "TP02",
    "modalita_pagamento": "MP05",
    "giorni_scadenza": 30,
    "iban": "IT60X0542811101000000123456",
}


def _cliente(**overrides: object) -> PartySnapshot:
    base: dict[str, object] = {
        "ragione_sociale": "Acme S.r.l.",
        "partita_iva": "12345678901",
        "codice_fiscale": None,
        "codice_sdi": "ABCDEFG",
        "pec": None,
        "indirizzo": "Corso Italia 5",
        "cap": "00100",
        "comune": "Roma",
        "provincia": "RM",
        "nazione": "IT",
        "email": None,
        "telefono": None,
        "sito_web": None,
    }
    base.update(overrides)
    return PartySnapshot(**base)  # type: ignore[arg-type]


def _line(
    numero: int,
    descrizione: str,
    quantita: str,
    prezzo: str,
    prezzo_totale: str,
    aliquota: str = "0.00",
    natura: str | None = "N2.2",
    unita: str | None = None,
) -> InvoiceLineRead:
    return InvoiceLineRead(
        id=uuid4(),
        invoice_id=uuid4(),
        numero_linea=numero,
        descrizione=descrizione,
        quantita=Decimal(quantita),
        unita_misura=unita,
        prezzo_unitario=Decimal(prezzo),
        sconto_percentuale=None,
        sconto_importo=None,
        prezzo_totale=Decimal(prezzo_totale),
        aliquota_iva=Decimal(aliquota),
        natura=natura,
        riferimento_normativo=FISCALE["riferimento_normativo"] if natura else None,  # type: ignore[arg-type]
    )


def _build_riepilogo_from(righe: list[InvoiceLineRead]) -> tuple:  # type: ignore[type-arg]
    return build_riepilogo(
        [
            ComputedLine(
                numero_linea=r.numero_linea,
                descrizione=r.descrizione,
                quantita=r.quantita,
                unita_misura=r.unita_misura,
                prezzo_unitario=r.prezzo_unitario,
                sconto_percentuale=r.sconto_percentuale,
                sconto_importo=r.sconto_importo,
                prezzo_totale=r.prezzo_totale,
                aliquota_iva=r.aliquota_iva,
                natura=r.natura,
                riferimento_normativo=r.riferimento_normativo,
            )
            for r in righe
        ]
    )


def _invoice(
    righe: list[InvoiceLineRead],
    *,
    cliente: PartySnapshot | None = None,
    emittente: PartySnapshot | None = None,
    bollo: str = "0.00",
    causale: str | None = "Consulenza tecnica",
    numero: int = 7,
) -> InvoiceForExport:
    imponibile, imposta, totale = sum_totals(_build_riepilogo_from(righe))
    return InvoiceForExport(
        anno=2026,
        numero=numero,
        data_emissione=date(2026, 8, 20),
        data_scadenza=date(2026, 9, 19),
        tipo_documento="TD01",
        divisa="EUR",
        imponibile=imponibile,
        imposta=imposta,
        bollo=Decimal(bollo),
        totale=totale,
        causale=causale,
        snapshot=InvoiceSnapshot(
            versione=SNAPSHOT_VERSIONE,
            emittente=emittente or EMITTENTE,
            cliente=cliente or _cliente(),
            fiscale=FISCALE,  # type: ignore[arg-type]
        ),
        righe=tuple(righe),
    )


# --- criterion 1: the official schema validates -----------------------------------


def test_a_single_line_invoice_validates() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza tecnica", "1.000000", "1500.000000", "1500.00")])
    )
    assert_valid(xml)


def test_a_five_line_invoice_validates() -> None:
    righe = [
        _line(n, f"Attivita {n}", "2.000000", "150.000000", "300.00", unita="ore")
        for n in range(1, 6)
    ]
    assert_valid(FatturaPAExporter().to_bytes(_invoice(righe)))


def test_an_invoice_with_a_negative_discount_line_validates() -> None:
    righe = [
        _line(1, "Consulenza", "1.000000", "1000.000000", "1000.00"),
        _line(2, "Sconto commerciale", "1.000000", "-100.000000", "-100.00"),
    ]
    xml = FatturaPAExporter().to_bytes(_invoice(righe))
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert root.findtext(".//ImportoTotaleDocumento") == "900.00"


def test_exactly_at_the_stamp_duty_threshold_there_is_no_dati_bollo() -> None:
    """Spec 14.1: 77.47 is not *above* the threshold."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "77.470000", "77.47")], bollo="0.00")
    )
    assert_valid(xml)
    assert etree.fromstring(xml).find(".//DatiBollo") is None


def test_one_cent_above_the_threshold_the_stamp_duty_is_declared() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "77.480000", "77.48")], bollo="2.00")
    )
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert root.findtext(".//BolloVirtuale") == "SI"
    assert root.findtext(".//ImportoBollo") == "2.00"
    # The duty is settled by the issuer, not charged to the customer (spec 7.2).
    assert root.findtext(".//ImportoTotaleDocumento") == "77.48"


# --- criterion 2: a hostile name cannot corrupt the file ---------------------------

HOSTILE = 'Rossi & C. <IdCodice>999</IdCodice> "#$@\\ ]]>'


def test_a_hostile_name_still_produces_a_schema_valid_file() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(ragione_sociale=HOSTILE),
        )
    )
    assert_valid(xml)


def test_a_hostile_name_round_trips_byte_for_byte() -> None:
    """The tree serialiser is the one escaping pass, so re-parsing must give back the
    domain value exactly. the previous system ran a value through escapeTypstText and then
    escapeXml, which put a literal backslash into an Agenzia delle Entrate record --
    that is what this asserts cannot happen."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(ragione_sociale=HOSTILE),
        )
    )
    root = etree.fromstring(xml)
    denominazioni = [element.text for element in root.iter("Denominazione")]
    assert HOSTILE in denominazioni


def test_a_hostile_name_creates_no_element_the_exporter_did_not_create() -> None:
    """Verified by walking the tree, not by comparing strings: `<IdCodice>999` inside
    a name must be text, so the document must contain exactly the three `IdCodice`
    elements the exporter emits (transmitter, cedente, cessionario) and no fourth."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(ragione_sociale=HOSTILE),
        )
    )
    root = etree.fromstring(xml)
    assert len(list(root.iter("IdCodice"))) == 3
    assert not [element.text for element in root.iter("IdCodice") if element.text == "999"]


def test_a_hostile_description_and_causale_are_equally_inert() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, HOSTILE, "1.000000", "100.000000", "100.00")], causale=HOSTILE)
    )
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert root.findtext(".//Descrizione") == HOSTILE
    assert root.findtext(".//Causale") == HOSTILE


def test_a_code_point_xml_cannot_represent_is_refused_not_emitted() -> None:
    with pytest.raises(ValueError, match="non rappresentabile in XML"):
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza\x0b", "1.000000", "100.000000", "100.00")],
            )
        )


# --- an astral-plane emoji and a legitimate accented name, both round trip --------


def test_an_astral_plane_emoji_is_refused_as_outside_latin_1() -> None:
    """FPR12's own `String*LatinType` family admits Basic Latin and Latin-1
    Supplement only, so a customer name carrying an emoji -- an astral-plane code
    point, U+1F600 -- must be refused by field name rather than emitted as a
    document the SdI would reject with no context at all."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(ragione_sociale="Acme \U0001f600 S.r.l."),
            )
        )
    assert caught.value.details["field"] == "ragione_sociale"


def test_a_legitimate_accented_italian_name_round_trips_and_validates() -> None:
    """Latin-1 Supplement covers ordinary accented Italian letters, so a real
    ragione sociale like this one must both validate and come back unchanged."""
    nome = "Caffè Perché S.r.l."
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(ragione_sociale=nome),
        )
    )
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert nome in [element.text for element in root.iter("Denominazione")]


# --- the prologue and the element order carried over from the previous system --------------------


def test_the_prologue_keeps_the_three_declarations_and_the_version_attribute() -> None:
    """`lxml`, not ElementTree, precisely for this: ElementTree prunes a prefix the
    document does not reference, and `ds:`/`xsi:` are unreferenced here. Removing a
    declaration from a prologue the SdI and every intermediary's validator have
    already accepted buys nothing."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    head = xml.decode("utf-8").split(">", 2)[1]
    assert xml.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")
    assert 'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"' in head
    assert 'xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"' in head
    assert 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' in head
    assert 'versione="FPR12"' in head
    # `pretty_print=True` puts a newline between the declaration and the root tag, so
    # `head` starts "\n<p:...": strip both characters, not only "<".
    assert head.lstrip("\n<").startswith("p:FatturaElettronica")


def test_formato_trasmissione_is_repeated_inside_dati_trasmissione() -> None:
    """Not redundant with the root attribute: the SdI reads it from here."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    assert etree.fromstring(xml).findtext(".//FormatoTrasmissione") == "FPR12"


def test_the_number_carries_the_year() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")], numero=7)
    )
    root = etree.fromstring(xml)
    assert root.findtext(".//Numero") == "2026/7"
    assert root.findtext(".//ProgressivoInvio") == "C28PZ"
    assert root.findtext(".//Data") == "2026-08-20"


def test_the_transmitter_id_may_be_the_fiscal_code() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    trasmittente = etree.fromstring(xml).find(".//IdTrasmittente")
    assert trasmittente.findtext("IdCodice") == "HMCRFT00A01H501K"


def test_the_vat_quartet_agrees_on_every_summary_group() -> None:
    """Two SdI checks applied as a pair: a zero rate with no Natura is rejected, and
    a Natura with a non-zero rate is rejected. All four must agree."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    riepilogo = etree.fromstring(xml).find(".//DatiRiepilogo")
    assert riepilogo.findtext("AliquotaIVA") == "0.00"
    assert riepilogo.findtext("Natura") == "N2.2"
    assert riepilogo.findtext("Imposta") == "0.00"
    assert riepilogo.findtext("EsigibilitaIVA") == "I"
    assert riepilogo.findtext("RiferimentoNormativo") == FISCALE["riferimento_normativo"]


def test_the_payment_block_carries_the_profile_values() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "1.000000", "100.000000", "100.00")])
    )
    root = etree.fromstring(xml)
    assert root.findtext(".//CondizioniPagamento") == "TP02"
    assert root.findtext(".//ModalitaPagamento") == "MP05"
    assert root.findtext(".//DataScadenzaPagamento") == "2026-09-19"
    assert root.findtext(".//ImportoPagamento") == "100.00"
    assert root.findtext(".//IBAN") == "IT60X0542811101000000123456"


def test_quantity_and_unit_price_keep_six_decimals() -> None:
    """Amount8DecimalType allows 2 to 8 decimals; three hours at 33,333333 EUR/h is
    the case `Numeric(12, 6)` exists for."""
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Consulenza", "3.000000", "33.333333", "100.00")])
    )
    root = etree.fromstring(xml)
    assert root.findtext(".//Quantita") == "3.000000"
    assert root.findtext(".//PrezzoUnitario") == "33.333333"
    assert root.findtext(".//PrezzoTotale") == "100.00"


# --- the recipient-code fallback, and the refusals --------------------------------


def test_a_customer_with_a_pec_but_no_sdi_gets_the_seven_zeroes_and_the_pec() -> None:
    """The correct fallback is not deducible from the schema, where the field is
    simply mandatory."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(codice_sdi=None, pec="acme@pec.it"),
        )
    )
    assert_valid(xml)
    root = etree.fromstring(xml)
    assert root.findtext(".//CodiceDestinatario") == "0000000"
    assert root.findtext(".//PECDestinatario") == "acme@pec.it"


def test_a_customer_with_neither_sdi_nor_pec_is_refused_by_field_name() -> None:
    """the previous system produced an empty `CodiceDestinatario` here: an invalid file, generated
    without an error."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(codice_sdi=None, pec=None),
            )
        )
    assert caught.value.details["entity"] == "customer"
    assert caught.value.details["field"] == "codice_sdi"


@pytest.mark.parametrize("field", ["indirizzo", "cap", "comune", "provincia"])
def test_a_missing_address_part_is_refused_by_field_name(field: str) -> None:
    """These are four real columns on `customers`. the previous system guessed them out of one
    free-text address with a regex over Italian street prefixes."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(**{field: ""}),
            )
        )
    assert caught.value.details["field"] == field


def test_a_cap_that_is_not_five_digits_is_refused() -> None:
    """FPR12's CAP is exactly `[0-9]{5}`, while `customers.cap` is String(10)."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(cap="2012"),
            )
        )
    assert caught.value.details["field"] == "cap"


def test_a_denomination_longer_than_the_schema_allows_is_refused_not_truncated() -> None:
    """`Denominazione` is String80LatinType; `customers.ragione_sociale` is
    String(255). Truncating a legal name on a fiscal document is worse than refusing
    to issue it."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(ragione_sociale="A" * 81),
            )
        )
    assert caught.value.details["field"] == "ragione_sociale"


def test_a_denomination_outside_latin_1_is_refused_by_field_name() -> None:
    """The schema's own pattern admits Basic Latin and Latin-1 Supplement only. An
    SdI rejection over a code point is worse than a message naming the field."""
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(ragione_sociale="Акме ООО"),
            )
        )
    assert caught.value.details["field"] == "ragione_sociale"


def test_a_country_code_that_is_not_a_country_code_is_refused() -> None:
    """What is left of the refusal this test used to assert.

    It read `test_a_foreign_customer_is_refused_because_the_slice_does_not_do_them`, and
    it was true: `check_party_exportable` raised on any `nazione != "IT"`. That is no
    longer the behaviour, and inverting the test is the honest way to record it -- a
    deleted test leaves nobody able to see that the decision changed, or when.

    What remains checked is that the field is a country code at all. `customers.nazione`
    is `String(2)`, which admits `"xx"` and `"1"` as readily as `"GB"`, and FPR12's
    `Nazione` wants two upper-case letters -- so a typo would otherwise reach the file and
    be rejected by the SdI after a register number had been spent on it.
    """
    for sbagliata in ("D", "de1", "1I"):
        with pytest.raises(ValidationFailed) as caught:
            FatturaPAExporter().to_bytes(
                _invoice(
                    [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                    cliente=_cliente(nazione=sbagliata),
                )
            )
        assert caught.value.details["field"] == "nazione"

    # And a real one is not refused, which is the whole change.
    assert_valid(
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(nazione="DE", codice_sdi=None, pec=None, provincia=""),
            )
        )
    )


def test_an_invoice_with_no_lines_is_refused() -> None:
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(_invoice([]))
    assert caught.value.details["field"] == "righe"


# --- fiscal-id normalisation, the highest-value line carried from the previous system ------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("IT12345678901", "12345678901"),
        ("12.345.678.901", "12345678901"),
        (" 12345678901 ", "12345678901"),
        ("rssmra80a01h501u", "RSSMRA80A01H501U"),
        ("1234567890", None),
        ("12345678901234567", None),
        ("", None),
        (None, None),
    ],
)
def test_a_fiscal_id_that_does_not_match_is_omitted_rather_than_malformed(
    raw: str | None, expected: str | None
) -> None:
    """The highest-value line in the previous system's generator: a malformed `IdCodice` is an
    outright rejection, while an absent element often passes."""
    assert normalise_fiscal_id(raw) == expected


def test_a_customer_with_an_unusable_vat_number_omits_the_element_entirely() -> None:
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
            cliente=_cliente(partita_iva=None, codice_fiscale="RSSMRA80A01H501U"),
        )
    )
    assert_valid(xml)
    cessionario = etree.fromstring(xml).find(".//CessionarioCommittente")
    assert cessionario.find(".//IdFiscaleIVA") is None
    assert cessionario.findtext(".//CodiceFiscale") == "RSSMRA80A01H501U"


def test_an_emitter_with_only_a_fiscal_code_and_no_vat_number_is_refused() -> None:
    """Unlike the customer side, `IdFiscaleIVA` is mandatory in the schema's own
    `DatiAnagraficiCedenteType` for the issuer, and an entity with no partita IVA is
    not a VAT subject in the first place -- it cannot be a `CedentePrestatore` at
    all, regardless of whether it has a fiscal code."""
    emittente_senza_piva = EMITTENTE.model_copy(update={"partita_iva": None})
    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Consulenza", "1.000000", "100.000000", "100.00")],
                emittente=emittente_senza_piva,
            )
        )
    assert caught.value.details["entity"] == "emitter_profile"
    assert caught.value.details["field"] == "partita_iva"


# --- criterion 8: the synthetic RF01 case, end to end through the XML -------------


def test_two_rates_produce_one_summary_group_each_with_group_computed_tax() -> None:
    righe = [
        _line(1, "Consulenza", "1.000000", "100.000000", "100.00", aliquota="22.00", natura=None),
        _line(2, "Formazione", "1.000000", "50.000000", "50.00", aliquota="10.00", natura=None),
        _line(3, "Assistenza", "1.000000", "25.000000", "25.00", aliquota="22.00", natura=None),
    ]
    invoice = _invoice(righe, causale=None)
    xml = FatturaPAExporter().to_bytes(invoice)
    assert_valid(xml)
    root = etree.fromstring(xml)
    groups = [
        (
            g.findtext("AliquotaIVA"),
            g.findtext("ImponibileImporto"),
            g.findtext("Imposta"),
        )
        for g in root.iter("DatiRiepilogo")
    ]
    assert groups == [("10.00", "50.00", "5.00"), ("22.00", "125.00", "27.50")]
    assert root.findtext(".//ImportoTotaleDocumento") == "207.50"
    assert root.find(".//Natura") is None


# --- determinism, which criterion 6 depends on ------------------------------------


def test_two_exports_of_the_same_invoice_are_byte_identical() -> None:
    invoice = _invoice([_line(1, "Consulenza", "1.000000", "1500.000000", "1500.00")])
    exporter = FatturaPAExporter()
    assert exporter.to_bytes(invoice) == exporter.to_bytes(invoice)


# --- a customer outside Italy ------------------------------------------------------


def _cliente_estero(**overrides: object) -> PartySnapshot:
    """A British customer, which is the shape that prompted this.

    A British VAT number of nine digits, no SDI code, no PEC, no province, and a
    postcode that is not five digits. Every one of those was a refusal until now, and
    together they made a foreign customer unrepresentable rather than merely awkward.
    """
    base: dict[str, object] = {
        "ragione_sociale": "Example Ltd",
        "partita_iva": "123456789",
        "codice_fiscale": None,
        "codice_sdi": None,
        "pec": None,
        "indirizzo": "1 Example Street",
        "cap": "00000",
        "comune": "London",
        "provincia": "",
        "nazione": "GB",
    }
    base.update(overrides)
    return _cliente(**base)


def test_a_foreign_customer_is_exportable_at_all() -> None:
    """The refusal this replaces was unconditional: `check_party_exportable` raised on
    any `nazione != "IT"` with "questo slice non emette fatture verso l'estero". That
    made the whole record a dead end -- a customer the CRM would hold and never invoice
    -- and the workaround it invited (a foreign VAT in `codice_fiscale`, the one fiscal
    field with no validation) stored the right number under the wrong name and would
    have written it into the wrong XML element."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Advisory", "10.000000", "150.000000", "1500.00")],
            cliente=_cliente_estero(),
        )
    )
    assert_valid(xml)


def test_a_foreign_vat_is_announced_as_its_own_country() -> None:
    """`IdPaese` was hard-coded to `IT`, which was true of every party the exporter could
    reach while a foreign customer was refused — and a lie the moment one got through.
    A British VAT number declared as Italian is not a cosmetic error: it is a claim about
    which register the number belongs to, made to the tax authority."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Advisory", "1.000000", "100.000000", "100.00")],
            cliente=_cliente_estero(),
        )
    )
    root = etree.fromstring(xml)
    cessionario = root.find(".//CessionarioCommittente/DatiAnagrafici/IdFiscaleIVA")
    assert cessionario is not None
    assert cessionario.findtext("IdPaese") == "GB"
    assert cessionario.findtext("IdCodice") == "123456789"

    # And the emitter is still Italian: the parameter has a default for a reason, and a
    # change that read the country off the wrong party would pass the assertion above.
    cedente = root.find(".//CedentePrestatore/DatiAnagrafici/IdFiscaleIVA")
    assert cedente is not None
    assert cedente.findtext("IdPaese") == "IT"


def test_a_foreign_recipient_is_routed_to_nobody() -> None:
    """`XXXXXXX` is what the specification reserves for a recipient the SdI does not
    route to. A foreign customer has no SDI code and no PEC and is not supposed to have
    either, so demanding one — as `check_recipient_routing` did — was demanding a value
    that does not exist."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Advisory", "1.000000", "100.000000", "100.00")],
            cliente=_cliente_estero(),
        )
    )
    root = etree.fromstring(xml)
    assert root.findtext(".//DatiTrasmissione/CodiceDestinatario") == "XXXXXXX"


def test_a_stray_sdi_code_on_a_foreign_customer_does_not_route_the_file_to_it() -> None:
    """The country is checked before the code, and this is why. A seven-character code
    left behind on a record whose country was later changed to `GB` — copied in by hand,
    or a leftover — would otherwise route somebody else's invoice to an Italian
    recipient's mailbox."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Advisory", "1.000000", "100.000000", "100.00")],
            cliente=_cliente_estero(codice_sdi="ABCDEFG"),
        )
    )
    root = etree.fromstring(xml)
    assert root.findtext(".//DatiTrasmissione/CodiceDestinatario") == "XXXXXXX"


def test_a_missing_province_is_refused_in_italy_and_accepted_outside_it() -> None:
    """`Provincia` is optional in FPR12 precisely so that a London address is not forced
    to invent one; requiring it of everybody was the second thing that made a foreign
    customer unrepresentable. It stays mandatory for an Italian address, where its
    absence is a real omission."""
    assert_valid(
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Advisory", "1.000000", "100.000000", "100.00")],
                cliente=_cliente_estero(provincia=""),
            )
        )
    )

    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice(
                [_line(1, "Advisory", "1.000000", "100.000000", "100.00")],
                cliente=_cliente(provincia=""),
            )
        )
    assert caught.value.details["field"] == "provincia"


# --- ORB-38: a foreign address is serialised the way the SdI expects it ---------------


def test_a_foreign_postcode_is_written_as_00000_and_kept_in_the_address() -> None:
    """ORB-38. FPR12's `CAP` is five digits and the technical specifications fill it
    with `00000` for an address outside Italy; the real postcode has no element of its
    own. Before this, `check_party_exportable` let `EC1V 9HL` through and `_sede`
    applied the five-digit pattern to it, so the number was spent and the export failed
    forever. The convention is applied by the writer, whatever the customer row holds:
    a London company keeps its postcode in the record, the PDF prints it, and the XML
    carries it at the end of `Indirizzo` so the document does not lose it."""
    cliente = _cliente_estero(cap="EC1V 9HL")
    check_party_exportable(cliente, "customer")

    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Advisory", "1.000000", "100.000000", "100.00")], cliente=cliente)
    )
    assert_valid(xml)
    sede = etree.fromstring(xml).find(".//CessionarioCommittente/Sede")
    assert sede is not None
    assert sede.findtext("CAP") == "00000"
    assert sede.findtext("Indirizzo") == "1 Example Street, EC1V 9HL"
    assert sede.findtext("Comune") == "London"
    assert sede.find("Provincia") is None
    assert sede.findtext("Nazione") == "GB"


def test_a_foreign_postcode_already_stored_as_the_convention_is_not_repeated() -> None:
    """`00000` is the SdI's placeholder, not a postcode: a record that already carries
    it (every foreign customer entered before ORB-38 does) gets a plain `Indirizzo`."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Advisory", "1.000000", "100.000000", "100.00")],
            cliente=_cliente_estero(cap="00000"),
        )
    )
    sede = etree.fromstring(xml).find(".//CessionarioCommittente/Sede")
    assert sede is not None
    assert sede.findtext("CAP") == "00000"
    assert sede.findtext("Indirizzo") == "1 Example Street"


def test_a_foreign_address_without_a_postcode_is_still_exportable() -> None:
    """A postcode is not something every country has, so its absence outside Italy is
    not an omission: `CAP` is the placeholder and `Indirizzo` is the address alone."""
    cliente = _cliente_estero(cap="")
    check_party_exportable(cliente, "customer")
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Advisory", "1.000000", "100.000000", "100.00")], cliente=cliente)
    )
    assert_valid(xml)
    sede = etree.fromstring(xml).find(".//CessionarioCommittente/Sede")
    assert sede is not None
    assert sede.findtext("CAP") == "00000"
    assert sede.findtext("Indirizzo") == "1 Example Street"


def test_a_province_stored_on_a_foreign_address_is_not_written() -> None:
    """The specifications fill `Provincia` only when `Nazione` is `IT`: it is the code
    of an Italian province, and a county or a state written there would be a false
    statement to the SdI. So whatever the record holds for a foreign customer, the
    element is omitted, and its shape is not a reason to refuse the emission."""
    cliente = _cliente_estero(cap="EC1V 9HL", provincia="Greater London")
    check_party_exportable(cliente, "customer")
    xml = FatturaPAExporter().to_bytes(
        _invoice([_line(1, "Advisory", "1.000000", "100.000000", "100.00")], cliente=cliente)
    )
    assert_valid(xml)
    sede = etree.fromstring(xml).find(".//CessionarioCommittente/Sede")
    assert sede is not None
    assert sede.find("Provincia") is None


def test_the_emitter_s_italian_address_is_untouched_by_the_foreign_convention() -> None:
    """`_sede` writes both parties. The emitter is Italian and keeps its real CAP and
    its province; a change that applied the placeholder to everybody would pass the
    foreign tests above and misreport the issuer's own address."""
    xml = FatturaPAExporter().to_bytes(
        _invoice(
            [_line(1, "Advisory", "1.000000", "100.000000", "100.00")],
            cliente=_cliente_estero(cap="EC1V 9HL"),
        )
    )
    sede = etree.fromstring(xml).find(".//CedentePrestatore/Sede")
    assert sede is not None
    assert sede.findtext("CAP") == "20124"
    assert sede.findtext("Provincia") == "MI"
    assert sede.findtext("Indirizzo") == "Via Vittorio Veneto 12"


def test_an_italian_cap_that_is_not_five_digits_is_still_refused_before_the_number() -> None:
    """The other direction of the same coherence: the convention is for a foreign
    address only. An Italian customer with a British-looking postcode is a data error
    and is refused by the pre-check, not written as `00000`."""
    with pytest.raises(ValidationFailed) as caught:
        check_party_exportable(_cliente(cap="EC1V 9HL"), "customer")
    assert caught.value.details["field"] == "cap"


def test_a_foreign_address_too_long_to_carry_its_postcode_is_refused_before_the_number() -> None:
    """`Indirizzo` is `String60LatinType`, and it now carries the postcode as well. The
    pre-check measures the same composite the writer emits, so a refusal happens before
    the register number is consumed and names the field the user can shorten. It is
    the whole reason `check_party_exportable` and `_sede` share one function for the
    address text."""
    lungo = "Flat 12, Bartholomew House, 20-22 Old Street, Clerkenwell"
    assert len(lungo) <= _INDIRIZZO_MAX < len(f"{lungo}, EC1V 9HL")
    cliente = _cliente_estero(indirizzo=lungo, cap="EC1V 9HL")

    with pytest.raises(ValidationFailed) as caught:
        check_party_exportable(cliente, "customer")
    assert caught.value.details["field"] == "indirizzo"

    with pytest.raises(ValidationFailed) as caught:
        FatturaPAExporter().to_bytes(
            _invoice([_line(1, "Advisory", "1.000000", "100.000000", "100.00")], cliente=cliente)
        )
    assert caught.value.details["field"] == "indirizzo"


def test_a_missing_comune_is_refused_outside_italy_as_well() -> None:
    """`Comune` is `String60LatinType`, one to sixty characters, and has no
    `minOccurs="0"`: the schema wants a city for every address. The pre-check dropped it
    from the mandatory list for a foreign party along with `cap` and `provincia`, which
    let an emission through that `export_xml` could never serialise. Same hole as the
    postcode, closed the same way."""
    with pytest.raises(ValidationFailed) as caught:
        check_party_exportable(_cliente_estero(comune=""), "customer")
    assert caught.value.details["field"] == "comune"


# --- the widths, checked before a number is spent -----------------------------------


def test_a_name_too_long_for_the_schema_is_refused_by_the_pre_check() -> None:
    """`check_party_exportable` is called by `InvoiceService.issue` *before* the register
    number is consumed, and used to check presence only. `customers.ragione_sociale` is
    `String(255)` against FPR12's 80, so an ordinary consortium name passed, the emission
    committed, and every later export raised forever — leaving annulment as the only
    remedy for a document that was never wrong, only unprintable.

    Refused before the number is spent costs one correction. Refused after costs a hole
    in the register.
    """
    lungo = "Consorzio Nazionale Servizi Integrati per la Logistica Societa Cooperativa"
    assert len(lungo) > 0
    with pytest.raises(ValidationFailed) as caught:
        check_party_exportable(_cliente(ragione_sociale=lungo * 2), "customer")
    assert caught.value.details["field"] == "ragione_sociale"


def test_a_cap_that_is_not_five_digits_is_refused_by_the_pre_check() -> None:
    """`customers.cap` is `String(10)`; the schema wants exactly five digits."""
    with pytest.raises(ValidationFailed) as caught:
        check_party_exportable(_cliente(cap="2012"), "customer")
    assert caught.value.details["field"] == "cap"
