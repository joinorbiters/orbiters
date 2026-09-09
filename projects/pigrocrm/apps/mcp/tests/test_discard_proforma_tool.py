"""`discard_proforma` (ORB-37): the one removal an agent is allowed on the invoicing
surface, and the line it stops at.

A proforma is the only document an agent shapes from the MCP: `create_proforma` makes
it, `replace_proforma_lines` rewrites it. Removing one it got wrong is the natural end of
that shaping, and leaving an empty or wrong draft in the list was the alternative until
this tool existed. The removal is the same soft delete the application performs, and it
stops exactly where the application stops: at anything that is not a proforma, before
`InvoiceService.soft_delete` and the table CHECK behind it get to refuse a consumed
number for their own reasons.
"""

from typing import Any

from mcp import Client
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.schemas import CustomerCreate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService
from pigrocrm.core.invoices.schemas import InvoiceCreate, InvoiceLineIn
from pigrocrm.core.invoices.service import InvoiceService
from pigrocrm.core.storage import LocalFileStorage

RIGA = {"descrizione": "Consulenza", "quantita": "2", "prezzo_unitario": "100.00"}


def _customer(session: Session) -> str:
    # The regime is the install's own configuration, set as the system and not as the
    # agent, for the reason `test_full_cycle.py` spells out at its own fixture.
    FiscalProfileService(session).upsert(FiscalProfileUpsert(codice_regime="RF19"), Actor.system())
    customer = CustomerService(session).create(
        CustomerCreate(ragione_sociale="Bozze S.r.l.", partita_iva="12345678901"),
        Actor(id=None, type="mcp", role="admin"),
    )
    return str(customer.id)


async def test_a_proforma_draft_is_discarded_and_is_gone_from_the_reads(
    server: Any, mcp_session: Session
) -> None:
    customer_id = _customer(mcp_session)
    async with Client(server) as client:
        created = await client.call_tool(
            "create_proforma", {"customer_id": customer_id, "righe": [RIGA]}
        )
        assert not created.is_error, created.content[0].text
        invoice_id = created.structured_content["id"]
        assert created.structured_content["tipo"] == "proforma"

        discarded = await client.call_tool("discard_proforma", {"invoice_id": invoice_id})
        assert not discarded.is_error, discarded.content[0].text
        assert discarded.structured_content == {"id": invoice_id, "scartata": True}

        # Gone from every read, not flagged: the soft delete is invisible to the surface.
        read = await client.call_tool("get_invoice", {"invoice_id": invoice_id})
        assert read.is_error
        listed = await client.call_tool("list_invoices", {"customer_id": customer_id})
        assert [item["id"] for item in listed.structured_content["items"]] == []


async def test_anything_that_is_not_a_proforma_is_refused_before_the_service_is_reached(
    server: Any, mcp_session: Session, tmp_path: Any
) -> None:
    """A fattura, even one still in draft, is not the agent's to remove: the same guard
    `replace_proforma_lines` applies, and the same wording, so the refusal explains
    itself rather than leaking the service's own message about numbers."""
    customer_id = _customer(mcp_session)
    fattura = InvoiceService(mcp_session, LocalFileStorage(tmp_path / "fatture")).create(
        InvoiceCreate(
            customer_id=customer_id,
            tipo="fattura",
            righe=[InvoiceLineIn(**RIGA)],
        ),
        Actor(id=None, type="user", role="admin"),
    )
    async with Client(server) as client:
        refused = await client.call_tool("discard_proforma", {"invoice_id": str(fattura.id)})
        assert refused.is_error
        assert "da MCP si modificano solo le proforma" in refused.content[0].text
        # And the draft is still there.
        read = await client.call_tool("get_invoice", {"invoice_id": str(fattura.id)})
        assert not read.is_error, read.content[0].text
        assert read.structured_content["tipo"] == "fattura"
