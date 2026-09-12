"""PostHog on the MCP surface (ORB-186): off without a key, and with one, every tool
call reaches the client with the actor's identity and the space as a group."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from mcp import Client
from posthog import Posthog
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.storage import LocalFileStorage
from pigrocrm_mcp import analytics
from pigrocrm_mcp.server import build_server

KEY = "phc_test_only_never_a_real_project"


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Posthog, list[dict[str, Any]]]]:
    """A real client whose `capture` is observed instead of sent: the adapter builds
    the payload and calls this, so what is asserted is what PostHog would receive."""
    client = Posthog(KEY, host="https://eu.i.posthog.com", sync_mode=True, disabled=False)
    events: list[dict[str, Any]] = []

    def record(*args: Any, **kwargs: Any) -> None:
        # `Client.capture(event, *, distinct_id=..., properties=...)`: the name travels
        # positionally, the rest by keyword. Normalised so the assertions read one shape.
        events.append({**kwargs, "event": kwargs.get("event", args[0] if args else None)})

    monkeypatch.setattr(client, "capture", record)
    try:
        yield client, events
    finally:
        client.shutdown()


def test_without_a_key_nothing_is_installed(mcp_session: Session, tmp_path: Path) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.posthog_key == ""
    mcp = build_server(
        lambda: mcp_session,
        lambda: Actor(id=None, type="mcp", role="admin"),
        LocalFileStorage(tmp_path),
        settings,
    )
    # The same call `build_server` made, repeated by hand: it answers False and the
    # server is the plain one every other test in this package drives.
    assert (
        analytics.install(mcp, settings, lambda: Actor(id=None, type="mcp", role="admin")) is False
    )


def test_the_space_group_is_the_root_slug_or_root() -> None:
    assert analytics.space_group(Settings(_env_file=None)) == "root"  # type: ignore[call-arg]
    assert analytics.space_group(Settings(_env_file=None, root_slug="studio")) == "studio"  # type: ignore[call-arg]


def test_the_identity_is_the_actor_and_the_space() -> None:
    user_id = uuid4()
    identify = analytics.identity_for(
        lambda: Actor(id=user_id, type="user", role="collaboratore"), "studio"
    )
    identity = identify(None, None)
    assert identity is not None
    assert identity.distinct_id == str(user_id)
    assert identity.groups == {"spazio": "studio"}
    assert identity.properties == {"ruolo": "collaboratore", "via": "user"}
    # An actor without an id (the fixtures' admin) stays anonymous rather than sharing
    # one made-up person across every installation.
    assert (
        analytics.identity_for(lambda: Actor(id=None, type="mcp", role="admin"), "root")(None, None)
        is None
    )


async def test_with_a_key_a_tool_call_reaches_posthog_with_the_actor(
    mcp_session: Session, tmp_path: Path, captured: tuple[Posthog, list[dict[str, Any]]]
) -> None:
    client, events = captured
    user_id = uuid4()
    settings = Settings(_env_file=None, posthog_key=KEY, root_slug="studio")  # type: ignore[call-arg]
    actor = Actor(id=user_id, type="user", role="admin")
    # Built without a key so `build_server` installs nothing, then installed by hand with
    # the observed client: what is under test is the wiring, not PostHog's network.
    mcp = build_server(
        lambda: mcp_session, lambda: actor, LocalFileStorage(tmp_path), Settings(_env_file=None)
    )  # type: ignore[call-arg]
    assert analytics.install(mcp, settings, lambda: actor, client) is True

    async with Client(mcp) as agent:
        tools = await agent.list_tools()
        await agent.call_tool("describe_schema", {"entity_type": "customer"})

    names = [event.get("event") for event in events]
    assert "$mcp_tool_call" in names, names
    call = next(event for event in events if event.get("event") == "$mcp_tool_call")
    assert call["distinct_id"] == str(user_id)
    assert call["properties"]["$mcp_tool_name"] == "describe_schema"
    assert call["properties"]["$groups"] == {"spazio": "studio"}
    assert call["properties"]["$mcp_is_error"] is False
    # And the schema an agent learns is untouched: no injected `context` argument.
    describe = next(tool for tool in tools.tools if tool.name == "describe_schema")
    assert "context" not in (describe.input_schema.get("properties") or {})
