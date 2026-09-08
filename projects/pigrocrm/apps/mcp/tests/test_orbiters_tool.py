"""`list_orbiters_signups`: the one MCP read on the `orbiters` database.

Builds its own server, like `test_mcp_dashboard.py`, because the tool must be pointed at
the test container rather than at whatever `Settings()`' default `database_url` names:
the tool derives the `orbiters` URL from `settings.database_url`, so the settings handed
to `build_server` are the whole of its wiring.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import Engine, text

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.orbiters import SignupCreate, SignupService, ensure_orbiters_database
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm_mcp.context import ScopedSessionProvider
from pigrocrm_mcp.server import build_server

ADMIN = Actor(id=None, type="mcp", role="admin")
COLLABORATORE = Actor(id=None, type="mcp", role="collaboratore")


def _payload(result: Any) -> dict[str, Any]:
    return result.structured_content or json.loads(result.content[0].text)


@pytest.fixture
def settings(mcp_engine: Engine) -> Settings:
    return Settings(
        database_url=mcp_engine.url.render_as_string(hide_password=False),
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def seeded(settings: Settings) -> Iterator[list[str]]:
    engine = ensure_orbiters_database(settings)
    session = session_factory(engine)()
    addresses = ["uno@studio.it", "due@studio.it"]
    for address in addresses:
        SignupService(session).subscribe(
            SignupCreate(
                email=address,
                nome="Ada",
                cognome="Lovelace",
                linkedin_url="https://www.linkedin.com/in/ada",
            )
        )
    try:
        yield addresses
    finally:
        session.execute(text("DELETE FROM signups"))
        session.commit()
        session.close()
        engine.dispose()


def _server(mcp_engine: Engine, settings: Settings, actor: Actor, tmp_path: Path):
    return build_server(
        ScopedSessionProvider(session_factory(mcp_engine)),
        lambda: actor,
        LocalFileStorage(tmp_path),
        settings,
    )


async def test_an_admin_reads_the_list_newest_first(
    mcp_engine: Engine, settings: Settings, seeded: list[str], tmp_path: Path
) -> None:
    async with Client(_server(mcp_engine, settings, ADMIN, tmp_path)) as client:
        result = await client.call_tool("list_orbiters_signups", {})
    body = _payload(result)
    assert body["totale"] == 2
    assert [item["email"] for item in body["iscrizioni"]] == list(reversed(seeded))


async def test_the_list_carries_the_name_and_the_profile_it_was_given(
    mcp_engine: Engine, settings: Settings, seeded: list[str], tmp_path: Path
) -> None:
    """Whoever reads this list writes to these people: the name is what an assistant
    needs in order to draft that message, and the profile is who they are."""
    async with Client(_server(mcp_engine, settings, ADMIN, tmp_path)) as client:
        result = await client.call_tool("list_orbiters_signups", {})
    item = _payload(result)["iscrizioni"][0]
    assert (item["nome"], item["cognome"]) == ("Ada", "Lovelace")
    assert item["linkedin_url"] == "https://www.linkedin.com/in/ada"


async def test_limit_pages_the_list_but_not_the_total(
    mcp_engine: Engine, settings: Settings, seeded: list[str], tmp_path: Path
) -> None:
    async with Client(_server(mcp_engine, settings, ADMIN, tmp_path)) as client:
        result = await client.call_tool("list_orbiters_signups", {"limit": 1})
    body = _payload(result)
    assert body["totale"] == 2
    assert len(body["iscrizioni"]) == 1


async def test_a_collaborator_is_refused(
    mcp_engine: Engine, settings: Settings, seeded: list[str], tmp_path: Path
) -> None:
    async with Client(_server(mcp_engine, settings, COLLABORATORE, tmp_path)) as client:
        result = await client.call_tool("list_orbiters_signups", {})
    assert result.is_error
    assert "admin" in result.content[0].text.lower()


async def test_the_tool_is_listed_and_subscribe_is_not(
    mcp_engine: Engine, settings: Settings, tmp_path: Path
) -> None:
    async with Client(_server(mcp_engine, settings, ADMIN, tmp_path)) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert "list_orbiters_signups" in names
    assert not [
        name for name in names if "subscribe" in name or "signup" in name and "list" not in name
    ]
