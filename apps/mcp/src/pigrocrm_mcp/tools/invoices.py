"""Thin calls into `InvoiceService`, plus the declaration of what MCP deliberately
cannot reach.

An agent may **prepare**. It may not emit. See `apps/mcp/tests/test_mcp_invoice_ban.py`
for the three reasons, and note that the mechanism is the absence of a tool rather than
an authorisation check: R10 is open, so a PAT inherits the owner's full role and an
administrative token would pass any check written here.
"""

from datetime import date
from typing import Any
from uuid import UUID

from pigrocrm.core.errors import Conflict
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import (
    InvoiceCreate,
    InvoiceLineIn,
    InvoiceListQuery,
    PaymentState,
)
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm_mcp.context import McpContext

# Operations that must **never** be reachable from MCP. Asserted to be exactly these
# four names by the ban test: adding a tool for one of them breaks the build, and
# removing a name without adding the tool breaks it too.
MCP_FORBIDDEN_OPERATIONS: frozenset[str] = frozenset(
    {
        "issue_invoice",
        "annul_invoice",
        "mark_transmitted_externally",
        "update_fiscal_profile",
    }
)

# Public service methods with no tool that are **not** forbidden -- they simply have no
# audience on the agentic surface. Each carries its reason, so the distinction between
# "must never be exposed" and "happens not to be exposed" stays visible.
#
# `render_pdf` is deliberately absent from this table: it names a method that was
# never implemented. `InvoiceService`'s only artefact method is `produce_artifacts`,
# which is classified below and is what `render_proforma_pdf` actually calls.
MCP_UNEXPOSED_OPERATIONS: dict[str, str] = {
    "update": "note interne e campi custom: nessun agente ha motivo di scriverli, e "
    "la causale e' congelata dopo l'emissione",
    "soft_delete": "la spec dello slice 1 ha gia' deciso che l'MCP non espone delete "
    "distruttivi",
    "confirm_proforma": "e' la conferma umana che precede l'emissione: l'agente "
    "prepara, la persona conferma",
    "export_xml": "l'XML esiste solo per una fattura emessa, e l'MCP non emette; "
    "get_invoice_xml_url restituisce l'URL di uno gia' prodotto",
    "produce_artifacts": "esposto come render_proforma_pdf, che rifiuta una fattura "
    "e restituisce solo l'artefatto PDF",
    "download": "l'MCP non restituisce mai byte, solo identificativi e URL "
    "(spec slice 2 §7)",
    "lines": "get_invoice restituisce gia' la fattura con le sue righe",
    "snapshot": "lettura interna del profilo fiscale, senza actor e senza audience",
    "get": "esposto come get_invoice / describe_fiscal_profile",
}

# Which operation name each public service method belongs to, for the operations that
# *are* exposed or forbidden. `get` appears in MCP_UNEXPOSED_OPERATIONS because both
# services define one and the tools call the domain-specific wrappers below.
SERVICE_METHOD_TO_OPERATION: dict[str, str] = {
    "list": "list_invoices",
    "create": "create_proforma",
    "replace_lines": "replace_proforma_lines",
    "set_payment_state": "set_invoice_payment_state",
    "describe": "describe_fiscal_profile",
    "issue": "issue_invoice",
    "annul": "annul_invoice",
    "mark_transmitted_externally": "mark_transmitted_externally",
    "upsert": "update_fiscal_profile",
}


def _invoices(context: McpContext) -> InvoiceService:
    return InvoiceService(context.session, context.storage)


def search(context: McpContext, query: InvoiceListQuery) -> dict[str, Any]:
    page = _invoices(context).list(query, context.actor)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": str(page.next_cursor) if page.next_cursor else None,
    }


def get(context: McpContext, invoice_id: str) -> dict[str, Any]:
    service = _invoices(context)
    invoice = service.get(UUID(invoice_id), context.actor)
    return {
        **invoice.model_dump(mode="json"),
        "righe": [
            line.model_dump(mode="json")
            for line in service.lines(UUID(invoice_id), context.actor)
        ],
    }


def create_proforma(context: McpContext, data: dict[str, Any]) -> dict[str, Any]:
    """`tipo` is forced to `proforma` here rather than taken from the caller: this is
    the only creation an agent performs, and letting it choose would put a draft
    invoice -- one button away from a consumed number -- on the agentic surface."""
    payload = {**data, "tipo": "proforma"}
    return _invoices(context).create(InvoiceCreate(**payload), context.actor).model_dump(
        mode="json"
    )


def _require_proforma(service: InvoiceService, invoice_id: UUID, context: McpContext) -> None:
    invoice = service.get(invoice_id, context.actor)
    if invoice.tipo != "proforma":
        raise Conflict(
            "invoice",
            "da MCP si modificano solo le proforma: una fattura la prepara e la emette "
            "una persona",
            tipo=invoice.tipo,
            stato=invoice.stato,
        )


def replace_proforma_lines(
    context: McpContext, invoice_id: str, righe: list[dict[str, Any]]
) -> dict[str, Any]:
    service = _invoices(context)
    identifier = UUID(invoice_id)
    _require_proforma(service, identifier, context)
    return service.replace_lines(
        identifier, [InvoiceLineIn(**riga) for riga in righe], context.actor
    ).model_dump(mode="json")


def render_proforma_pdf(context: McpContext, invoice_id: str) -> dict[str, Any]:
    service = _invoices(context)
    identifier = UUID(invoice_id)
    _require_proforma(service, identifier, context)
    artifacts = service.produce_artifacts(identifier, context.actor)
    # A proforma always yields exactly one artefact (the PDF: `produce_artifacts`
    # only appends the XML for an issued fattura), but `next(... if a.kind == "pdf")`
    # reads correctly even if that invariant ever changes, rather than assuming
    # `artifacts[0]` is the PDF.
    artifact = next(a for a in artifacts if a.kind == "pdf")
    return {
        **artifact.model_dump(mode="json"),
        # An identifier and a URL, never the bytes: a base64 PDF inside a model's own
        # context is waste and risk (slice 2 §7).
        "download_url": f"/api/invoices/{invoice_id}/pdf",
    }


def xml_url(context: McpContext, invoice_id: str) -> dict[str, Any]:
    """The URL of an already-produced XML. Never the bytes, and never a production:
    producing one requires an issued invoice, and MCP does not issue."""
    invoice = _invoices(context).get(UUID(invoice_id), context.actor)
    if invoice.xml_document_id is None:
        raise Conflict(
            "invoice",
            "questa fattura non ha ancora un file XML: va prodotto dall'applicazione",
            stato=invoice.stato,
        )
    return {
        "invoice_id": invoice_id,
        "numero": f"{invoice.anno}/{invoice.numero}",
        "download_url": f"/api/invoices/{invoice_id}/xml",
        "hash_sha256": invoice.xml_hash_sha256,
    }


def set_payment_state(
    context: McpContext, invoice_id: str, stato_pagamento: str, data_incasso: str | None
) -> dict[str, Any]:
    return (
        _invoices(context)
        .set_payment_state(
            UUID(invoice_id),
            PaymentState(
                stato_pagamento=stato_pagamento,  # type: ignore[arg-type]
                data_incasso=date.fromisoformat(data_incasso) if data_incasso else None,
            ),
            context.actor,
        )
        .model_dump(mode="json")
    )


def describe_fiscal_profile(context: McpContext) -> dict[str, Any]:
    return FiscalProfileService(context.session).describe(context.actor)
