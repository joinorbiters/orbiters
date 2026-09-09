"""From a frozen `InvoiceForExport` to PDF bytes, through slice 2's pipeline unchanged.

Separate from `render/pdf.py` on purpose: that module is the generic Pandoc/Typst
runner and the only place in the codebase that spawns a process, and it must stay
ignorant of invoices. This module knows about invoices and nothing about subprocesses.

Every value in the scope is a **string already formatted for display**, produced by
`totals.py`'s formatters. Amounts are never handed to the template as `Decimal` for the
template to format, and never re-parsed from text: the previous system applied a percentage to a
total it had read back out of a formatted string, and that is the class of defect this
separation removes.
"""

from decimal import Decimal
from typing import Any

from pigrocrm.core.config import Settings
from pigrocrm.core.invoices.naming import numero_completo
from pigrocrm.core.invoices.schemas import InvoiceForExport
from pigrocrm.core.invoices.totals import format_amount_2, format_amount_8, format_rate
from pigrocrm.core.render.pdf import ASSETS_DIR, build_header, render_pdf
from pigrocrm.core.templates.renderer import render_template

INVOICE_TEMPLATE = ASSETS_DIR / "template-invoice.md"
PROFORMA_TEMPLATE = ASSETS_DIR / "template-proforma.md"

# In the body of the document, not a watermark: a watermark is a thing a print can
# lose, and this is one of four independent mechanisms keeping a proforma from being
# paid as an invoice. Asserted verbatim by the tests, so it is a constant rather than
# a string typed twice.
PROFORMA_DECLARATION = "FATTURA PROFORMA - NON COSTITUISCE FATTURA"

CODICE_DESTINATARIO_FALLBACK = "0000000"
_EMPTY = ""


def indirizzo_display(party: dict[str, Any]) -> str:
    """The customer's address as one line, the way the country writes it (ORB-55).

    Computed here rather than assembled in the template, which is the direction this
    module already leans: every other value the template reads is a string this file
    formatted, and `template-invoice.md` hard-coded `({{cliente.provincia}})` -- so a
    London customer read `1 Old Street, EC1V 9HL London () GB` on the document, empty
    parentheses and all. A template cannot make that decision well: the province is a
    field of an Italian address and the parentheses are punctuation that belongs to it,
    and `{{#if}}` around the pair would have to be repeated in every template that ever
    prints an address.

    Italy keeps the shape it always had, `CAP Comune (PR)`. Outside it, the postcode is
    printed as the record holds it (`EC1V 9HL`, not the `00000` the XML carries -- see
    `fatturapa.CAP_ESTERO`) and the province is not printed at all. An Italian record
    with no province yet, which a proforma may well have, loses the parentheses rather
    than printing them empty: the same defect in the domestic case.
    """
    nazione = (party.get("nazione") or "").strip().upper()
    pezzi = [
        pezzo
        for pezzo in ((party.get("cap") or "").strip(), (party.get("comune") or "").strip())
        if pezzo
    ]
    provincia = (party.get("provincia") or "").strip().upper()
    if nazione == "IT" and provincia:
        pezzi.append(f"({provincia})")
    if nazione:
        pezzi.append(nazione)
    indirizzo = (party.get("indirizzo") or "").strip()
    resto = " ".join(pezzi)
    if indirizzo and resto:
        return f"{indirizzo}, {resto}"
    return indirizzo or resto


def build_scope(export: InvoiceForExport, *, riferimento: str | None) -> dict[str, Any]:
    """What the template can read.

    Built entirely from the snapshot and the stored totals. The live `emitter_profile`
    and `fiscal_profile` are not consulted, which is what makes a re-render a year
    later produce the same bytes (criterion 6) rather than a document that quietly
    reflects whatever the configuration says today.
    """
    snapshot = export.snapshot
    cliente = snapshot.cliente
    fiscale = snapshot.fiscale
    codice_destinatario = (cliente.codice_sdi or "").strip() or (
        CODICE_DESTINATARIO_FALLBACK if (cliente.pec or "").strip() else _EMPTY
    )
    bollo = (
        f"Imposta di bollo di {format_amount_2(export.bollo)} EUR assolta in modo "
        "virtuale a carico dell'emittente."
        if export.bollo > Decimal("0.00")
        else _EMPTY
    )
    return {
        "emittente": snapshot.emittente.model_dump(mode="json"),
        "cliente": {
            **cliente.model_dump(mode="json"),
            "codice_destinatario": codice_destinatario,
            "indirizzo_display": indirizzo_display(cliente.model_dump(mode="json")),
        },
        "fiscale": fiscale.model_dump(mode="json"),
        "fattura": {
            "etichetta": "Fattura" if riferimento is None else "Fattura proforma",
            "numero": (
                riferimento
                if riferimento is not None
                else numero_completo(export.anno, export.numero)
            ),
            "data": export.data_emissione.isoformat(),
            "data_scadenza": (export.data_scadenza.isoformat() if export.data_scadenza else _EMPTY),
            "causale": export.causale or _EMPTY,
            # The whole line, or nothing: the template wraps it in `{{#if}}`, so a
            # document with no period prints no label with an empty value after it.
            "periodo_competenza": _periodo_competenza(export),
            "imponibile": format_amount_2(export.imponibile),
            "imposta": format_amount_2(export.imposta),
            "bollo": format_amount_2(export.bollo),
            "totale": format_amount_2(export.totale),
            "dichiarazione_bollo": bollo,
            "dichiarazione_regime": _dichiarazione_regime(export),
        },
        "righe": [
            {
                "numero_linea": str(riga.numero_linea),
                "descrizione": riga.descrizione,
                "quantita": format_amount_8(riga.quantita),
                "unita_misura": riga.unita_misura or _EMPTY,
                "prezzo_unitario": format_amount_2(riga.prezzo_unitario),
                "aliquota_iva": format_rate(riga.aliquota_iva),
                "prezzo_totale": format_amount_2(riga.prezzo_totale),
            }
            for riga in export.righe
        ],
    }


def _periodo_competenza(export: InvoiceForExport) -> str:
    """`dd/mm/yyyy - dd/mm/yyyy`, the way an Italian reader writes a span of days, or
    `""` when the document has no period (ORB-61). Both ends or neither is the row's
    own CHECK, so a half period cannot reach this function."""
    if export.competenza_da is None or export.competenza_a is None:
        return _EMPTY
    return f"{export.competenza_da:%d/%m/%Y} - {export.competenza_a:%d/%m/%Y}"


def _dichiarazione_regime(export: InvoiceForExport) -> str:
    """The normative declaration the footer prints: the one the lines carry.

    Until ORB-32 the footer read `fiscale.riferimento_normativo` straight from the
    snapshot, which is the profile's *domestic* text; a non-resident customer's lines
    carry `N2.1` and the art. 7-ter reference instead, and a PDF that contradicted its
    own XML is what that produced. The distinct references are kept in line order and
    joined with a space, so an invoice whose lines ever carried two different ones
    shows both rather than the first. The profile text remains the fallback for lines
    with no reference at all, which is what an `RF01` invoice has.
    """
    distinct: list[str] = []
    for riga in export.righe:
        if riga.riferimento_normativo and riga.riferimento_normativo not in distinct:
            distinct.append(riga.riferimento_normativo)
    if distinct:
        return " ".join(distinct)
    return export.snapshot.fiscale.riferimento_normativo or _EMPTY


def render_invoice_pdf(
    export: InvoiceForExport, *, riferimento: str | None, settings: Settings
) -> tuple[str, bytes]:
    """`(compiled_markdown, pdf_bytes)`.

    `riferimento is None` picks the fiscal template; a reference string picks the
    proforma one, which carries `PROFORMA_DECLARATION` in its body. The choice is made
    from the row's own data, never from a caller's flag.

    The page header and footer come from `build_header`, exactly as slice 2's offer
    render does, so the issuer's identity, logo and contacts are laid out once and in
    one place rather than repeated in every body template.
    """
    template = INVOICE_TEMPLATE if riferimento is None else PROFORMA_TEMPLATE
    scope = build_scope(export, riferimento=riferimento)
    markdown = render_template(template.read_text(encoding="utf-8"), scope)
    header = build_header(scope["emittente"])
    return markdown, render_pdf(markdown, header_typst=header, settings=settings)
