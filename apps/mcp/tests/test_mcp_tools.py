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


# --- Fix round 1: update_* schemas must be discoverable, and every argument- ---
# --- conversion failure must render like every other domain error.          ---


async def test_update_customer_schema_lists_the_real_modifiable_fields(server) -> None:
    """A model calling list_tools() must see the actual field names it can send in
    `changes`, not an opaque `{"type": "object"}` it has to guess or infer from
    create_customer's sibling schema."""
    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    changes_schema = tools["update_customer"].input_schema["properties"]["changes"]
    assert "ragione_sociale" in changes_schema["properties"]
    assert "partita_iva" in changes_schema["properties"]


async def test_update_deal_schema_lists_the_real_modifiable_fields(server) -> None:
    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    changes_schema = tools["update_deal"].input_schema["properties"]["changes"]
    assert "probabilita" in changes_schema["properties"]
    assert "valore_previsto" in changes_schema["properties"]
    # move_deal, not update_deal, is the supported way to change stage -- the
    # schema must not invite an agent to try setting it here instead.
    assert "pipeline_stage_id" not in changes_schema["properties"]


async def test_update_person_schema_documents_what_detach_does(server) -> None:
    """`detach` reads as a bare boolean unless its schema explains the effect --
    the field name alone does not say it unlinks the person from their customer."""
    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    changes_schema = tools["update_person"].input_schema["properties"]["changes"]
    detach_schema = changes_schema["properties"]["detach"]
    description = detach_schema.get("description", "").lower()
    assert description
    assert "client" in description or "cliente" in description


async def test_create_deal_documents_the_expected_date_format(server) -> None:
    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    create_deal_tool = tools["create_deal"]
    assert "YYYY-MM-DD" in (create_deal_tool.description or "")


async def test_a_malformed_identifier_produces_guidance_not_a_stack_trace(
    server, mcp_session: Session
) -> None:
    """§8.2: an error must be actionable by a model. `uuid.UUID("not-a-uuid")`
    raises a bare `ValueError` with an English, unstructured message; the guard
    must render it the same way as every other domain error."""
    async with Client(server) as client:
        result = await client.call_tool("get_customer", {"customer_id": "not-a-uuid"})

    assert result.is_error
    message = result.content[0].text
    assert "errors.pydantic.dev" not in message
    assert "badly formed" not in message
    assert "Valore atteso" in message
    assert "cerca" in message.lower()


async def test_a_wrong_typed_value_inside_changes_produces_guidance(
    server, mcp_session: Session
) -> None:
    """Fix 1 makes `changes` a real, typed schema; this proves the type-checking
    that now happens when building the update model still comes back through the
    guard's rendering, not as a raw pydantic dump with a errors.pydantic.dev link."""
    PipelineService(mcp_session).seed_defaults(ADMIN)
    async with Client(server) as client:
        customer = _payload(await client.call_tool("create_customer", {"ragione_sociale": "ACME"}))
        deal = _payload(
            await client.call_tool("create_deal", {"nome": "X", "customer_id": customer["id"]})
        )
        result = await client.call_tool(
            "update_deal", {"deal_id": deal["id"], "changes": {"probabilita": "not-a-number"}}
        )

    assert result.is_error
    message = result.content[0].text
    assert "errors.pydantic.dev" not in message
    assert "probabilita" in message
    assert "Valore atteso" in message


async def test_a_limit_out_of_range_produces_guidance_naming_the_range(
    server, mcp_session: Session
) -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_customers", {"limit": 500})

    assert result.is_error
    message = result.content[0].text
    assert "errors.pydantic.dev" not in message
    assert "200" in message
    assert "Valore atteso" in message


# --- The WithJsonSchema override must not disturb the ordinary, valid path. ---


async def test_update_customer_still_applies_a_valid_changes_payload(server) -> None:
    async with Client(server) as client:
        customer = _payload(await client.call_tool("create_customer", {"ragione_sociale": "ACME"}))
        updated = _payload(
            await client.call_tool(
                "update_customer",
                {"customer_id": customer["id"], "changes": {"ragione_sociale": "ACME Srl"}},
            )
        )

    assert updated["ragione_sociale"] == "ACME Srl"


async def test_update_person_can_still_detach_via_changes(server) -> None:
    async with Client(server) as client:
        customer = _payload(await client.call_tool("create_customer", {"ragione_sociale": "ACME"}))
        person = _payload(
            await client.call_tool(
                "create_person", {"nome": "Mario", "customer_id": customer["id"]}
            )
        )
        updated = _payload(
            await client.call_tool(
                "update_person", {"person_id": person["id"], "changes": {"detach": True}}
            )
        )

    assert updated["customer_id"] is None


async def test_update_deal_still_applies_a_valid_changes_payload(
    server, mcp_session: Session
) -> None:
    PipelineService(mcp_session).seed_defaults(ADMIN)
    async with Client(server) as client:
        customer = _payload(await client.call_tool("create_customer", {"ragione_sociale": "ACME"}))
        deal = _payload(
            await client.call_tool("create_deal", {"nome": "X", "customer_id": customer["id"]})
        )
        updated = _payload(
            await client.call_tool(
                "update_deal", {"deal_id": deal["id"], "changes": {"probabilita": 42}}
            )
        )

    assert updated["probabilita"] == 42
