"""`log_time` is the most valuable agentic operation in this product and the safest one:
"Claude, ho fatto tre ore ieri sul progetto Rossi" is the weekly time saving slice 1 §1
makes the criterion of existence for every feature. It is the opposite of
`issue_invoice`: reversible, attributed, and bounded to one deal and one day."""

from mcp import Client


async def test_log_time_writes_and_is_attributable_to_the_agent(
    server, seeded_deal_id, seeded_user_id, mcp_session
) -> None:
    async with Client(server) as client:
        created = await client.call_tool(
            "log_time",
            {
                "deal_id": str(seeded_deal_id),
                "user_id": str(seeded_user_id),
                "data": "2026-03-10",
                # A string with two decimal places, not a bare `3`: `HoursArg` accepts
                # `float | str`, and a JSON integer arrives as a Python `float` whose
                # `Decimal` conversion carries only as many places as the float itself
                # (`Decimal('3.0')`, not `Decimal('3.00')`) -- this asserts the exact
                # wire value `TimeEntryRead` returns, so the input is written the same
                # way a client's own numeric text field would send it.
                "ore": "3.50",
                "descrizione": "Analisi requisiti",
            },
        )
        entry = created.structured_content
        assert entry["ore"] == "3.50"

        timeline = await client.call_tool(
            "get_timeline", {"entity_type": "time_entry", "entity_id": entry["id"]}
        )
        assert timeline.structured_content["entries"][0]["actor_type"] == "mcp"


async def test_the_eleven_excluded_tools_do_not_exist(server) -> None:
    """Criterion 9's first half, from the client's own point of view: an agent trying to
    recalculate rates finds no tool to call. Eleven, not the ten slice 4 §11 enumerated:
    `unarchive_cost_category` was missing from that list by omission -- it is
    `archive_cost_category` in the other direction, and settles the same question of
    which categories the CRM offers -- and was added to the ban rather than left as a
    method nobody had decided about."""
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    for forbidden in (
        "recalculate_rates",
        "update_user_rates",
        "update_deal_rate",
        "create_cost_category",
        "update_cost_category",
        "archive_cost_category",
        "unarchive_cost_category",
        "bind_time_to_invoice",
        "close_period",
        "reopen_period",
        "get_fiscal_estimate",
    ):
        assert forbidden not in names
    assert {"log_time", "describe_rates", "list_cost_categories"} <= names


async def test_a_bad_argument_comes_back_as_guidance_not_a_pydantic_dump(
    server, seeded_deal_id, seeded_user_id
) -> None:
    """Spec §8.2: an LLM that receives a numeric code retries at random; one that
    receives a diagnosis stops or corrects. `HoursArg` keeps the SDK from rejecting the
    value ahead of `_guard`. Checked the same way every other tool's identical guard
    test does (`test_mcp_tools.py`) -- a rejected tool call comes back as a
    `CallToolResult` with `is_error=True`, not as a raised Python exception from
    `call_tool` itself."""
    async with Client(server) as client:
        result = await client.call_tool(
            "log_time",
            {
                "deal_id": str(seeded_deal_id),
                "user_id": str(seeded_user_id),
                "data": "2026-03-10",
                "ore": "molte",
                "descrizione": "x",
            },
        )
    assert result.is_error
    assert "errors.pydantic.dev" not in result.content[0].text


async def test_the_deal_resource_carries_the_hours_block(
    server, seeded_deal_id, seeded_user_id
) -> None:
    async with Client(server) as client:
        await client.call_tool(
            "log_time",
            {
                "deal_id": str(seeded_deal_id),
                "user_id": str(seeded_user_id),
                "data": "2026-03-10",
                "ore": "8.00",
                "descrizione": "Sviluppo",
            },
        )
        rendered = (await client.read_resource(f"deal://{seeded_deal_id}")).contents[0].text
    assert "## Ore" in rendered
    assert "Ore consuntivate: 8.00" in rendered
    assert "Stato: **in corso**" in rendered
