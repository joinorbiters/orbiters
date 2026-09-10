"""`confirm_proforma` (ORB-132): the step between shaping a proforma and issuing it.

Until this existed the surface could create a proforma, rewrite it and discard it, and
`issue_invoice` (behind `mcp_full_access`) refused it: the service issues a *confirmed*
proforma, and nothing here confirmed one. The confirmation itself touches no register
and consumes nothing, which is why it sits with the other proforma tools and not in
`privileged.py`; the irreversible step stays where it was.
"""

from typing import Any

from mcp import Client
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.customers.schemas import CustomerCreate
from pigrocrm.core.customers.service import CustomerService
from pigrocrm.core.fiscal.schemas import FiscalProfileUpsert
from pigrocrm.core.fiscal.service import FiscalProfileService

RIGA = {"descrizione": "Consulenza", "quantita": "2", "prezzo_unitario": "100.00"}


def _customer(session: Session) -> str:
    FiscalProfileService(session).upsert(FiscalProfileUpsert(codice_regime="RF19"), Actor.system())
    customer = CustomerService(session).create(
        CustomerCreate(ragione_sociale="Bozze S.r.l.", partita_iva="12345678901"),
        Actor(id=None, type="mcp", role="admin"),
    )
    return str(customer.id)


async def test_a_draft_proforma_with_lines_is_confirmed(server: Any, mcp_session: Session) -> None:
    customer_id = _customer(mcp_session)
    async with Client(server) as client:
        created = await client.call_tool(
            "create_proforma", {"customer_id": customer_id, "righe": [RIGA]}
        )
        assert not created.is_error, created.content[0].text
        invoice_id = created.structured_content["id"]
        assert created.structured_content["stato"] == "bozza"

        confirmed = await client.call_tool("confirm_proforma", {"invoice_id": invoice_id})
        assert not confirmed.is_error, confirmed.content[0].text
        assert confirmed.structured_content["id"] == invoice_id
        assert confirmed.structured_content["stato"] == "confermata"
        # Still a proforma, still without a number: nothing fiscal happened.
        assert confirmed.structured_content["tipo"] == "proforma"
        assert confirmed.structured_content["numero"] is None

        again = await client.call_tool("get_invoice", {"invoice_id": invoice_id})
        assert again.structured_content["stato"] == "confermata"


async def test_a_proforma_without_lines_is_refused_with_the_field_named(
    server: Any, mcp_session: Session
) -> None:
    customer_id = _customer(mcp_session)
    async with Client(server) as client:
        created = await client.call_tool(
            "create_proforma", {"customer_id": customer_id, "righe": []}
        )
        assert not created.is_error, created.content[0].text
        invoice_id = created.structured_content["id"]
        refused = await client.call_tool("confirm_proforma", {"invoice_id": invoice_id})
        assert refused.is_error
        assert "senza righe" in refused.content[0].text


async def test_a_confirmed_proforma_is_not_confirmed_twice(
    server: Any, mcp_session: Session
) -> None:
    customer_id = _customer(mcp_session)
    async with Client(server) as client:
        created = await client.call_tool(
            "create_proforma", {"customer_id": customer_id, "righe": [RIGA]}
        )
        invoice_id = created.structured_content["id"]
        first = await client.call_tool("confirm_proforma", {"invoice_id": invoice_id})
        assert not first.is_error, first.content[0].text
        second = await client.call_tool("confirm_proforma", {"invoice_id": invoice_id})
        assert second.is_error
        assert "confermata" in second.content[0].text


async def test_the_tool_is_on_the_default_surface_not_behind_the_switch(server: Any) -> None:
    """Confirming consumes nothing and goes back, so it is not one of the operations an
    installation has to open with `mcp_full_access`; the fixture server is a default
    installation and lists it."""
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert "confirm_proforma" in names
        assert "issue_invoice" not in names
