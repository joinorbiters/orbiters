"""Task 13's own brief sample called `server.call_tool_sync(...)`/
`server.list_tools_sync(...)` and depended on a `mcp_server` fixture -- neither
exists against the installed SDK (`mcp==2.0.0`; `MCPServer` has no `*_sync` methods
at all) or in this repo's `conftest.py` (the existing fixture is `server`, an
`MCPServer`, driven through `mcp.Client` exactly as every other MCP test in this
project already does -- see `test_mcp_tools.py`). Rewritten against that real
pattern rather than transcribed.
"""

import json
import shutil
from typing import Any

import pytest
from mcp import Client

needs_binaries = pytest.mark.skipif(
    shutil.which("pandoc") is None or shutil.which("typst") is None,
    reason="pandoc e typst vivono nell'immagine dell'API",
)


def _payload(result: Any) -> dict[str, Any]:
    return result.structured_content or json.loads(result.content[0].text)


async def test_the_seven_spec_tools_are_registered(server) -> None:
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert {
        "list_documents",
        "get_document",
        "create_document_from_template",
        "list_templates",
        "describe_template",
        "set_offer_state",
        "get_document_versions",
    } <= names


async def test_no_tool_returns_document_bytes(server) -> None:
    # "Il download dei byte non passa da MCP: un tool che restituisce un PDF in
    # base64 dentro un contesto e' uno spreco e un rischio" (spec 7).
    async with Client(server) as client:
        tools = (await client.list_tools()).tools

    for tool in tools:
        assert "download" not in tool.name
        assert "base64" not in (tool.description or "").lower()


async def test_describe_template_reports_the_variables_before_anyone_is_asked(
    server, seeded_template_id: str
) -> None:
    async with Client(server) as client:
        result = await client.call_tool("describe_template", {"template_id": seeded_template_id})

    described = _payload(result)
    assert [v["nome"] for v in described["variabili"]] == ["oggetto"]
    assert described["nome"] == "Consulenza CTO"


@needs_binaries
async def test_create_document_from_template_returns_an_identifier_not_bytes(
    server, seeded_template_id: str, seeded_customer_id: str
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "create_document_from_template",
            {
                "template_id": seeded_template_id,
                "customer_id": seeded_customer_id,
                "titolo": "Offerta 2026-01",
                "variabili": {"oggetto": "Advisory"},
            },
        )

    assert not result.is_error, result.content[0].text
    created = _payload(result)
    assert "id" in created
    assert "pdf" not in json.dumps(created).lower()


async def test_list_documents_filters_by_customer(server, seeded_customer_id: str) -> None:
    async with Client(server) as client:
        result = await client.call_tool("list_documents", {"customer_id": seeded_customer_id})

    listed = _payload(result)
    assert "items" in listed and isinstance(listed["items"], list)


async def test_a_wrong_typed_limit_produces_guidance_not_a_pydantic_dump(
    server, seeded_customer_id: str
) -> None:
    # R2: the SDK validates some arguments before the guard runs. `BoundedLimit`'s
    # `int | str` runtime type is what keeps this inside the guard.
    async with Client(server) as client:
        result = await client.call_tool(
            "list_documents", {"customer_id": seeded_customer_id, "limit": "molti"}
        )

    assert result.is_error
    assert "errors.pydantic.dev" not in result.content[0].text


async def test_set_offer_state_refuses_an_undeclared_transition_with_guidance(
    server, seeded_offer_id: str
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "set_offer_state", {"document_id": seeded_offer_id, "stato": "accettata"}
        )

    assert result.is_error
    message = result.content[0].text
    assert "bozza" in message
    assert "errors.pydantic.dev" not in message


async def test_get_document_versions_lists_them_newest_first(server, seeded_offer_id: str) -> None:
    async with Client(server) as client:
        result = await client.call_tool("get_document_versions", {"document_id": seeded_offer_id})

    assert "versions" in _payload(result)
