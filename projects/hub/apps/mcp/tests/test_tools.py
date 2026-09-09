"""`list_signups`: the hub's one MCP read today, over its own database."""

import json
from typing import Any

from mcp import Client
from sqlalchemy.orm import Session, sessionmaker

from orbiters_core.schemas import SignupCreate
from orbiters_core.service import SignupService
from orbiters_mcp.server import build_server


def _payload(result: Any) -> dict[str, Any]:
    return result.structured_content or json.loads(result.content[0].text)


def _seed(factory: sessionmaker[Session], addresses: list[str]) -> None:
    session = factory()
    try:
        for address in addresses:
            SignupService(session).subscribe(
                SignupCreate(
                    email=address,
                    nome="Ada",
                    cognome="Lovelace",
                    linkedin_url="https://www.linkedin.com/in/ada",
                )
            )
    finally:
        session.close()


async def test_the_list_is_newest_first_and_the_total_counts_everything(
    factory: sessionmaker[Session],
) -> None:
    _seed(factory, ["uno@studio.it", "due@studio.it"])
    async with Client(build_server(factory)) as client:
        result = await client.call_tool("list_signups", {"limit": 1})
    body = _payload(result)
    assert body["totale"] == 2
    assert [item["email"] for item in body["iscrizioni"]] == ["due@studio.it"]
    item = body["iscrizioni"][0]
    assert (item["nome"], item["cognome"]) == ("Ada", "Lovelace")
    assert item["linkedin_url"] == "https://www.linkedin.com/in/ada"


async def test_the_tool_is_listed_and_nothing_writes(factory: sessionmaker[Session]) -> None:
    async with Client(build_server(factory)) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert names == {"list_signups"}
