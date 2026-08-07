import json

from mcp import Client
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.fields.schemas import FieldDefinitionCreate
from pigrocrm.core.fields.service import FieldDefinitionService
from pigrocrm.core.pipeline.service import PipelineService

ADMIN = Actor(id=None, type="mcp", role="admin")


def _payload(result) -> dict:
    return result.structured_content or json.loads(result.content[0].text)


async def test_every_tool_from_the_spec_is_exposed(server) -> None:
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert {
        "describe_schema",
        "refresh_schema",
        "create_customer",
        "update_customer",
        "get_customer",
        "search_customers",
        "archive_customer",
        "create_person",
        "update_person",
        "get_person",
        "search_people",
        "archive_person",
        "create_deal",
        "update_deal",
        "get_deal",
        "search_deals",
        "move_deal",
        "archive_deal",
        "list_pipeline_stages",
        "get_timeline",
    } <= names


async def test_no_destructive_delete_tool_exists(server) -> None:
    """An agent misreading 'elimina i deal chiusi' must not be able to destroy rows."""
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert not [name for name in names if name.startswith("delete_")]


async def test_the_full_journey_an_agent_would_take(server, mcp_session: Session) -> None:
    """Spec success criterion 2: Claude does the whole job through MCP, discovering a
    custom field nobody hardcoded."""
    FieldDefinitionService(mcp_session).create(
        FieldDefinitionCreate(
            entity_type="customer",
            key="settore",
            label="Settore",
            field_type="select",
            options=["IT", "Retail"],
        ),
        ADMIN,
    )
    PipelineService(mcp_session).seed_defaults(ADMIN)

    async with Client(server) as client:
        schema = _payload(await client.call_tool("describe_schema", {"entity_type": "customer"}))
        assert [f["key"] for f in schema["custom_fields"]] == ["settore"]

        customer = _payload(
            await client.call_tool(
                "create_customer",
                {
                    "ragione_sociale": "ACME Srl",
                    "partita_iva": "12345678901",
                    "custom_fields": {"settore": "IT"},
                },
            )
        )
        assert customer["custom_fields"] == {"settore": "IT"}

        person = _payload(
            await client.call_tool(
                "create_person",
                {"nome": "Mario", "cognome": "Rossi", "customer_id": customer["id"]},
            )
        )
        assert person["customer_id"] == customer["id"]

        deal = _payload(
            await client.call_tool(
                "create_deal", {"nome": "Progetto X", "customer_id": customer["id"]}
            )
        )

        stages = _payload(await client.call_tool("list_pipeline_stages", {}))["stages"]
        offerta = next(s for s in stages if s["nome"] == "Offerta")
        moved = _payload(
            await client.call_tool("move_deal", {"deal_id": deal["id"], "stage_id": offerta["id"]})
        )
        assert moved["pipeline_stage_id"] == offerta["id"]

        timeline = _payload(
            await client.call_tool("get_timeline", {"entity_type": "deal", "entity_id": deal["id"]})
        )["entries"]

    # Criterion 3: the timeline distinguishes the agent from a human.
    assert {entry["actor_type"] for entry in timeline} == {"mcp"}
    assert "stage_changed" in {entry["kind"] for entry in timeline}


async def test_an_invalid_custom_value_returns_guidance_naming_the_options(
    server, mcp_session: Session
) -> None:
    FieldDefinitionService(mcp_session).create(
        FieldDefinitionCreate(
            entity_type="customer",
            key="settore",
            label="Settore",
            field_type="select",
            options=["IT", "Retail"],
        ),
        ADMIN,
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "create_customer",
            {"ragione_sociale": "Beta", "custom_fields": {"settore": "Altro"}},
        )

    assert result.is_error
    message = result.content[0].text
    assert "IT" in message and "Retail" in message
    assert "Valore atteso" in message


async def test_a_permission_error_tells_the_agent_to_ask_the_user(mcp_session: Session) -> None:
    from pigrocrm_mcp.server import build_server

    readonly = Actor(id=None, type="mcp", role="readonly")
    server = build_server(lambda: mcp_session, lambda: readonly)

    async with Client(server) as client:
        result = await client.call_tool("create_customer", {"ragione_sociale": "ACME"})

    assert result.is_error
    message = result.content[0].text
    assert "readonly" in message
    assert "manualmente" in message


async def test_search_customers_finds_by_free_text(server, mcp_session: Session) -> None:
    async with Client(server) as client:
        await client.call_tool("create_customer", {"ragione_sociale": "ACME Srl"})
        await client.call_tool("create_customer", {"ragione_sociale": "Beta Spa"})
        found = _payload(await client.call_tool("search_customers", {"search": "acme"}))

    assert [c["ragione_sociale"] for c in found["items"]] == ["ACME Srl"]


async def test_archive_customer_is_reversible_and_blocks_on_active_deals(
    server, mcp_session: Session
) -> None:
    PipelineService(mcp_session).seed_defaults(ADMIN)
    async with Client(server) as client:
        customer = _payload(await client.call_tool("create_customer", {"ragione_sociale": "ACME"}))
        deal = _payload(
            await client.call_tool("create_deal", {"nome": "X", "customer_id": customer["id"]})
        )

        blocked = await client.call_tool("archive_customer", {"customer_id": customer["id"]})
        assert blocked.is_error
        assert "deal attivi" in blocked.content[0].text

        await client.call_tool("archive_deal", {"deal_id": deal["id"]})
        ok = await client.call_tool("archive_customer", {"customer_id": customer["id"]})

    assert not ok.is_error


async def test_create_person_without_a_customer_is_allowed(server) -> None:
    """A contact may exist before anyone knows their employer -- `customer_id` must
    stay optional at the actual MCP boundary, not merely on the underlying schema."""
    async with Client(server) as client:
        person = _payload(
            await client.call_tool("create_person", {"nome": "Giulia", "cognome": "Bianchi"})
        )

    assert person["customer_id"] is None


async def test_move_deal_to_a_won_stage_settles_probability_through_the_tool(
    server, mcp_session: Session
) -> None:
    """`move_deal` must not re-decide probability itself -- it delegates to
    `DealService.move_stage`, which is the single authority on 'won at 60%' being
    unreachable. This proves that delegation survives the MCP boundary end to end."""
    PipelineService(mcp_session).seed_defaults(ADMIN)
    async with Client(server) as client:
        customer = _payload(await client.call_tool("create_customer", {"ragione_sociale": "ACME"}))
        deal = _payload(
            await client.call_tool(
                "create_deal",
                {"nome": "Progetto Y", "customer_id": customer["id"], "probabilita": 20},
            )
        )

        stages = _payload(await client.call_tool("list_pipeline_stages", {}))["stages"]
        vinto = next(s for s in stages if s["nome"] == "Vinto")
        moved = _payload(
            await client.call_tool("move_deal", {"deal_id": deal["id"], "stage_id": vinto["id"]})
        )

    assert moved["probabilita"] == 100
