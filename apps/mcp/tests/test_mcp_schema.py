import json

import pytest
from mcp import Client
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.fields.schemas import FieldDefinitionCreate
from pigrocrm.core.fields.service import FieldDefinitionService

ADMIN = Actor(id=None, type="mcp", role="admin")


def _payload(result) -> dict:
    return result.structured_content or json.loads(result.content[0].text)


async def test_describe_schema_lists_native_and_custom_fields(server, mcp_session: Session) -> None:
    FieldDefinitionService(mcp_session).create(
        FieldDefinitionCreate(
            entity_type="customer", key="settore", label="Settore", field_type="text"
        ),
        ADMIN,
    )
    async with Client(server) as client:
        result = await client.call_tool("describe_schema", {"entity_type": "customer"})

    body = _payload(result)
    assert "ragione_sociale" in body["native_fields"]
    assert any(field["key"] == "settore" for field in body["custom_fields"])


async def test_describe_schema_reads_live_so_a_new_field_appears_at_once(
    server, mcp_session: Session
) -> None:
    """Tool schemas are fixed at registration, so describe_schema must not be. This is
    how an agent notices a field added from the web app while the server was running."""
    async with Client(server) as client:
        before = _payload(await client.call_tool("describe_schema", {"entity_type": "deal"}))
        assert before["custom_fields"] == []

        FieldDefinitionService(mcp_session).create(
            FieldDefinitionCreate(
                entity_type="deal", key="rischio", label="Rischio", field_type="text"
            ),
            ADMIN,
        )
        after = _payload(await client.call_tool("describe_schema", {"entity_type": "deal"}))

    assert [f["key"] for f in after["custom_fields"]] == ["rischio"]


async def test_the_tool_list_is_advertised(server) -> None:
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert {"describe_schema", "refresh_schema"} <= names


async def test_refresh_schema_reports_what_it_rebuilt(server, mcp_session: Session) -> None:
    FieldDefinitionService(mcp_session).create(
        FieldDefinitionCreate(
            entity_type="customer", key="settore", label="Settore", field_type="text"
        ),
        ADMIN,
    )
    async with Client(server) as client:
        body = _payload(await client.call_tool("refresh_schema", {}))
    assert body["customer"] == 1


async def test_customer_resource_returns_readable_markdown(server, mcp_session: Session) -> None:
    """Resources exist so an agent can read before it acts."""
    from pigrocrm.core.customers.schemas import CustomerCreate
    from pigrocrm.core.customers.service import CustomerService

    customer = CustomerService(mcp_session).create(
        CustomerCreate(ragione_sociale="ACME Srl", partita_iva="12345678901"), ADMIN
    )
    async with Client(server) as client:
        result = await client.read_resource(f"customer://{customer.id}")

    text = result.contents[0].text
    assert "ACME Srl" in text
    assert "12345678901" in text
    assert "## Timeline" in text


async def test_an_unknown_resource_id_explains_itself(server) -> None:
    from uuid import uuid4

    async with Client(server) as client:
        with pytest.raises(Exception) as exc:
            await client.read_resource(f"customer://{uuid4()}")
    assert "non trovato" in str(exc.value).lower() or "not found" in str(exc.value).lower()
