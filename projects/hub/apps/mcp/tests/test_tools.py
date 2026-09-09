"""`list_signups`: the hub's one MCP read today, over its own database."""

import json
from typing import Any

from mcp import Client
from sqlalchemy import text
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


async def test_no_tool_subscribes_or_applies_on_somebody_elses_behalf(
    factory: sessionmaker[Session],
) -> None:
    async with Client(build_server(factory)) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert not [
        name for name in names if "subscribe" in name or "apply" in name or "request" in name
    ]


PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"


async def test_the_admin_tools_read_and_move_a_candidate_without_the_cv(
    factory: sessionmaker[Session],
) -> None:
    from decimal import Decimal

    from orbiters_core.freelancers import FreelancerService
    from orbiters_core.schemas import FreelancerCreate

    session = factory()
    try:
        row = FreelancerService(session).apply(
            FreelancerCreate(
                nome="Ada",
                cognome="Lovelace",
                email="ada@studio.it",
                tariffa_giornaliera=Decimal("450"),
                posizione="Backend developer",
                remoto="remoto",
            ),
            PDF,
            "cv.pdf",
            "application/pdf",
        )
    finally:
        session.close()

    async with Client(build_server(factory)) as client:
        listed = _payload(await client.call_tool("list_freelancers", {}))
        assert listed["totale"] == 1
        assert "cv_bytes" not in listed["items"][0]
        assert listed["items"][0]["cv_filename"] == "cv.pdf"

        moved = _payload(
            await client.call_tool(
                "set_freelancer_status",
                {"freelancer_id": str(row.id), "stato": "contattato", "note": "scritto oggi"},
            )
        )
        assert (moved["stato"], moved["note"]) == ("contattato", "scritto oggi")

        refused = await client.call_tool(
            "set_freelancer_status", {"freelancer_id": str(row.id), "stato": "forse"}
        )
        assert refused.is_error
        assert "stato" in refused.content[0].text

        missing = await client.call_tool("get_company", {"company_id": str(row.id)})
        assert missing.is_error

        names = {tool.name for tool in (await client.list_tools()).tools}
        assert names == {
            "list_signups",
            "list_freelancers",
            "get_freelancer",
            "set_freelancer_status",
            "list_companies",
            "get_company",
            "set_company_status",
        }
    session = factory()
    session.execute(text("DELETE FROM freelancers"))
    session.commit()
    session.close()
