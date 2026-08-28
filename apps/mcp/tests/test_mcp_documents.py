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


async def test_the_four_document_tools_the_audit_added_are_registered(server) -> None:
    """Each was reachable over REST and excluded from MCP with a reason that only said
    nobody had written the tool yet -- `TemplateService.preview` "non ha ancora
    un'audience agentica", `DocumentService.regenerate` "e' una decisione della persona
    che l'ha vista", `soft_delete`/`restore` "l'MCP non archivia documenti". None of the
    four decides anything a person has not already decided, and the last two are the
    archive/restore pair this surface already exposes for customers, deals, people,
    costs and time entries."""
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert {
        "preview_template",
        "regenerate_document_version",
        "archive_document",
        "restore_document",
    } <= names


async def test_preview_template_renders_without_creating_a_document(
    server, seeded_template_id: str, seeded_customer_id: str
) -> None:
    """`describe_template` says what a template wants; this says what the answers would
    produce. Nothing is written -- which is the whole reason it is safe to expose, and
    the reason it is useful: the agent checks the text before
    `create_document_from_template` freezes a version and a PDF."""
    async with Client(server) as client:
        result = await client.call_tool(
            "preview_template",
            {
                "template_id": seeded_template_id,
                # `cliente` is supplied by the caller here, unlike
                # `create_document_from_template`, which reads it off the record: a
                # preview is not filed under anything, so there is no record to read.
                "variabili": {"oggetto": "Advisory", "cliente": {"ragione_sociale": "ACME"}},
            },
        )
        assert not result.is_error, result.content[0].text
        assert _payload(result)["markdown"] == "Spett.le ACME — Advisory"

        listed = _payload(
            await client.call_tool("list_documents", {"customer_id": seeded_customer_id})
        )
    assert listed["items"] == []


async def test_preview_template_names_the_variable_it_is_missing(
    server, seeded_template_id: str
) -> None:
    """The failure mode that makes a preview worth having: it says which variable is
    missing, before the same omission costs a document and a rendered PDF."""
    async with Client(server) as client:
        result = await client.call_tool(
            "preview_template",
            {
                "template_id": seeded_template_id,
                "variabili": {"cliente": {"ragione_sociale": "ACME"}},
            },
        )

    assert result.is_error
    assert "oggetto" in result.content[0].text
    assert "errors.pydantic.dev" not in result.content[0].text


@needs_binaries
async def test_regenerate_reproduces_a_version_and_leaves_the_original_in_place(
    server, seeded_template_id: str, seeded_customer_id: str
) -> None:
    """Slice 2's reproducibility promise, exercised from the surface that now offers it:
    the new version is rendered from the old one's own frozen `template_id` and
    `variabili`, so its bytes hash the same, and the version it came from is still
    there. It adds; it does not overwrite."""
    async with Client(server) as client:
        created = _payload(
            await client.call_tool(
                "create_document_from_template",
                {
                    "template_id": seeded_template_id,
                    "customer_id": seeded_customer_id,
                    "titolo": "Offerta 2026-02",
                    "variabili": {"oggetto": "Advisory"},
                },
            )
        )
        regenerated = await client.call_tool(
            "regenerate_document_version", {"document_id": created["id"], "numero": 1}
        )
        assert not regenerated.is_error, regenerated.content[0].text
        assert _payload(regenerated)["numero"] == 2

        versions = _payload(
            await client.call_tool("get_document_versions", {"document_id": created["id"]})
        )["versions"]

    assert [v["numero"] for v in versions] == [2, 1]
    assert versions[0]["hash_sha256"] == versions[1]["hash_sha256"]


async def test_regenerate_refuses_a_version_that_was_never_generated_from_a_template(
    server, seeded_offer_id: str
) -> None:
    """The guard that makes this tool a reproduction rather than a creation: with no
    template and no variables stored on the source version there is nothing to
    reproduce, and the refusal says so instead of inventing a document."""
    async with Client(server) as client:
        result = await client.call_tool(
            "regenerate_document_version", {"document_id": seeded_offer_id, "numero": 1}
        )

    assert result.is_error
    assert "errors.pydantic.dev" not in result.content[0].text


async def test_regenerate_rejects_a_wrong_typed_version_number_with_guidance(
    server, seeded_offer_id: str
) -> None:
    """`VersionNumber` is `int | str` at runtime for the reason every other scalar
    parameter here is: a bare `int` lets the SDK reject the argument before `_guard`
    runs, and the agent gets a raw English pydantic dump. `_NUMERO` validates it inside
    the guarded call instead."""
    async with Client(server) as client:
        result = await client.call_tool(
            "regenerate_document_version", {"document_id": seeded_offer_id, "numero": "prima"}
        )

    assert result.is_error
    message = result.content[0].text
    assert "numero intero" in message
    assert "errors.pydantic.dev" not in message


async def test_a_document_archived_by_an_agent_can_be_restored_by_one(
    server, seeded_offer_id: str
) -> None:
    """Both, or neither. An agent that could archive a document and not bring it back
    would leave its own mistake correctable only by a person with a browser -- the exact
    asymmetry the audit found on customers, deals and people. The stored bytes are never
    touched by either half, so the restored document still has its PDF."""
    async with Client(server) as client:
        archived = await client.call_tool("archive_document", {"document_id": seeded_offer_id})
        assert not archived.is_error, archived.content[0].text
        assert (await client.call_tool("get_document", {"document_id": seeded_offer_id})).is_error

        restored = _payload(
            await client.call_tool("restore_document", {"document_id": seeded_offer_id})
        )
        assert restored["id"] == seeded_offer_id
        assert not (
            await client.call_tool("get_document", {"document_id": seeded_offer_id})
        ).is_error


async def test_describe_emitter_profile_reads_the_issuer_every_header_prints(
    server, seeded_template_id: str
) -> None:
    """`seeded_template_id` is the fixture that seeds the emitter profile, because
    rendering a document needs one -- which is the same reason
    `EmitterProfileService.get` is un-role-gated at the service layer: the PDF header
    needs it for every role, so there is no role for which this read is privileged. The
    write on that row (`upsert`) has no tool at all."""
    async with Client(server) as client:
        profile = _payload(await client.call_tool("describe_emitter_profile", {}))

    assert profile["ragione_sociale"] == "Humancraft di Ivan Sala"
    assert profile["partita_iva"] == "14518240966"
    # Storage keys, never bytes (spec slice 2 §7): the logo travels as a key the REST
    # API can serve, exactly like every other identifier on this surface.
    assert "logo_key" in profile
