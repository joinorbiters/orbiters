"""The MCP server over Streamable HTTP (ORB-170): who may call, and as whom.

Driven in-process: `httpx2.ASGITransport` around `create_app(...)`, and the SDK's own
client on top, so the wire is the real one and no port is opened. The root database is
the MCP suite's container; Task 5 adds spaces provisioned on the same server.
"""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import httpx2
import pytest
import pytest_asyncio
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import Engine, delete, select

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.pat_models import PersonalAccessToken
from pigrocrm.core.auth.pat_service import PatService
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm_mcp.http import McpHttpApp, create_app

EMAIL = "http-transport@prova.it"


@pytest.fixture(scope="module")
def http_settings(mcp_engine: Engine) -> Settings:
    return Settings(
        database_url=mcp_engine.url.render_as_string(hide_password=False),
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def root_token(mcp_engine: Engine) -> Iterator[tuple[str, UUID]]:
    """A collaboratore in the root database and a PAT of theirs; both removed after."""
    with session_factory(mcp_engine)() as session:
        user = UserService(session).create(
            UserCreate(
                email=EMAIL, password="lunghissima1", nome="Trasporto", ruolo="collaboratore"
            ),
            Actor.system(),
        )
        actor = Actor(id=user.id, type="user", role="collaboratore")
        _, raw = PatService(session, settings=Settings(_env_file=None)).create("prova", actor)  # type: ignore[call-arg]
        session.commit()
        user_id = user.id
    try:
        yield raw, user_id
    finally:
        with session_factory(mcp_engine)() as session:
            session.execute(delete(Activity).where(Activity.actor_id == user_id))
            session.execute(
                delete(PersonalAccessToken).where(PersonalAccessToken.user_id == user_id)
            )
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


@pytest_asyncio.fixture
async def served(http_settings: Settings) -> AsyncIterator[tuple[McpHttpApp, httpx2.AsyncClient]]:
    app = create_app(http_settings, overrides_ttl=0.0)
    async with app.lifespan():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://prova") as client:
            yield app, client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _authed(app: McpHttpApp, token: str) -> httpx2.AsyncClient:
    """A client of its own per call, with the bearer on every request, straight onto the app."""
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://prova", headers=_bearer(token)
    )


async def _tool_names(app: McpHttpApp, url: str, token: str) -> list[str]:
    async with (
        _authed(app, token) as authed,
        streamable_http_client(url, http_client=authed) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        return sorted(tool.name for tool in (await session.list_tools()).tools)


async def _call_tool(
    app: McpHttpApp, url: str, token: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    async with (
        _authed(app, token) as authed,
        streamable_http_client(url, http_client=authed) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments)
        text = result.content[0].text  # type: ignore[union-attr]
        return json.loads(text)


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "prova", "version": "0"},
    },
}
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_health_needs_no_credential(served: tuple[McpHttpApp, httpx2.AsyncClient]) -> None:
    _, client = served
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer non-un-pat"},
        {"Authorization": "Bearer pgc_sconosciuto"},
        {"Authorization": "Basic abc"},
    ],
)
async def test_without_a_valid_pat_the_answer_is_one_uniform_401(
    served: tuple[McpHttpApp, httpx2.AsyncClient], headers: dict[str, str]
) -> None:
    _, client = served
    response = await client.post("/mcp", json=INITIALIZE, headers={**ACCEPT, **headers})
    assert response.status_code == 401
    assert response.json() == {"detail": "Token non valido"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_a_revoked_token_is_indistinguishable_from_an_unknown_one(
    served: tuple[McpHttpApp, httpx2.AsyncClient], root_token: tuple[str, UUID], mcp_engine: Engine
) -> None:
    raw, user_id = root_token
    with session_factory(mcp_engine)() as session:
        service = PatService(session, settings=Settings(_env_file=None))  # type: ignore[call-arg]
        [record] = service.list(Actor(id=user_id, type="user", role="collaboratore"))
        service.revoke(record.id, Actor(id=user_id, type="user", role="collaboratore"))
        session.commit()
    _, client = served
    response = await client.post("/mcp", json=INITIALIZE, headers={**ACCEPT, **_bearer(raw)})
    assert response.status_code == 401
    assert response.json() == {"detail": "Token non valido"}


@pytest.mark.asyncio
async def test_only_the_bare_mcp_path_is_served(
    served: tuple[McpHttpApp, httpx2.AsyncClient], root_token: tuple[str, UUID]
) -> None:
    raw, _ = root_token
    _, client = served
    for path in ["/mcp/app", "/api/customers", "/", "/mcpx"]:
        response = await client.post(path, json=INITIALIZE, headers={**ACCEPT, **_bearer(raw)})
        assert response.status_code == 404, path
        assert response.json() == {"detail": "non trovato"}


@pytest.mark.asyncio
async def test_a_valid_pat_initialises_and_lists_the_tools(
    served: tuple[McpHttpApp, httpx2.AsyncClient], root_token: tuple[str, UUID]
) -> None:
    raw, _ = root_token
    app, _ = served
    names = await _tool_names(app, "http://prova/mcp", raw)
    assert "describe_schema" in names
    assert "create_customer" in names
    # The root's environment has mcp_full_access false: the fiscal tools are not there.
    assert "issue_invoice" not in names


@pytest.mark.asyncio
async def test_a_write_is_recorded_against_the_token_owner_as_an_agent(
    served: tuple[McpHttpApp, httpx2.AsyncClient], root_token: tuple[str, UUID], mcp_engine: Engine
) -> None:
    raw, user_id = root_token
    app, _ = served
    created = await _call_tool(
        app, "http://prova/mcp", raw, "create_customer", {"ragione_sociale": "Cliente via HTTP"}
    )
    with session_factory(mcp_engine)() as session:
        activity = session.scalars(
            select(Activity).where(Activity.entity_id == UUID(created["id"]))
        ).first()
    assert activity is not None
    assert activity.actor_type == "mcp"
    assert activity.actor_id == user_id


@pytest.mark.asyncio
async def test_the_token_use_is_stamped(
    served: tuple[McpHttpApp, httpx2.AsyncClient], root_token: tuple[str, UUID], mcp_engine: Engine
) -> None:
    raw, user_id = root_token
    app, _ = served
    await _tool_names(app, "http://prova/mcp", raw)
    with session_factory(mcp_engine)() as session:
        [record] = PatService(session).list(Actor(id=user_id, type="user", role="collaboratore"))
    assert record.last_used_at is not None
