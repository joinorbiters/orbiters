"""The MCP server over Streamable HTTP (ORB-170): who may call, and as whom.

Driven in-process: `httpx2.ASGITransport` around `create_app(...)`, and the SDK's own
client on top, so the wire is the real one and no port is opened. The root database is
the MCP suite's container; Task 5 adds spaces provisioned on the same server.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import anyio
import httpx2
import pytest
import pytest_asyncio
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import Engine, create_engine, delete, select, text

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.pat_models import PersonalAccessToken
from pigrocrm.core.auth.pat_service import PatService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.db.sidecar import drop_database
from pigrocrm.core.errors import Conflict
from pigrocrm.core.space_settings import SpaceSettingsService, SpaceSettingsUpdate
from pigrocrm.core.tenants import TenantService, TenantSignup, ensure_tenants_database
from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url
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


@pytest.mark.asyncio
async def test_the_lifespan_protocol_starts_the_app_serves_and_stops_it() -> None:
    """What a server drives, and the only path `lifespan()` does not cover.

    `uvicorn pigrocrm_mcp.http:app` never calls `lifespan()`: it sends `lifespan.startup`
    into `__call__` and expects `lifespan.startup.complete` back, serves requests, then
    sends `lifespan.shutdown`. No database is opened here -- `/health` answers before any
    space is resolved -- so this is the one test in the file that needs no container row.
    """
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return await inbox.get()

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    protocol = asyncio.create_task(app({"type": "lifespan"}, receive, send))
    await inbox.put({"type": "lifespan.startup"})
    with anyio.fail_after(10):
        while not sent:
            await anyio.sleep(0.01)
    assert sent == [{"type": "lifespan.startup.complete"}]

    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://prova") as client:
        response = await client.get("/health")
    assert response.json() == {"status": "ok"}

    await inbox.put({"type": "lifespan.shutdown"})
    with anyio.fail_after(10):
        await protocol
    assert sent == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]


class _LifespanThatFails:
    """Stands in for the SDK's Starlette app when its lifespan fails before it is ready.

    Its own `router`, because `_build` enters `starlette.router.lifespan_context(...)`
    and that is the only attribute of the real app it touches before the app is served.
    """

    def __init__(self) -> None:
        self.router = self

    @asynccontextmanager
    async def lifespan_context(self, app: Any) -> AsyncIterator[None]:
        raise RuntimeError("la lifespan non parte")
        yield  # pragma: no cover -- unreachable, and what makes this a context manager


class _ServerWhoseAppFails:
    def streamable_http_app(self, **kwargs: Any) -> Any:
        return _LifespanThatFails()


@pytest.mark.asyncio
async def test_a_space_lifespan_that_fails_to_start_answers_the_request_instead_of_hanging(
    served: tuple[McpHttpApp, httpx2.AsyncClient],
    root_token: tuple[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure arrives at the request that asked for the build, under a deadline.

    The deadline is the assertion: the task that enters a space's lifespan is not a
    child of the request, so a failure before it is ready used to leave the request
    waiting on an event nobody would ever set, holding the build lock and blocking every
    later build behind it. What the caller reads is the application's own 500, because
    `__call__` answers every failure of its own rather than letting one reach the server.
    """
    raw, _ = root_token
    _, client = served
    monkeypatch.setattr(
        "pigrocrm_mcp.http.build_server", lambda *args, **kwargs: _ServerWhoseAppFails()
    )
    with anyio.fail_after(10):
        response = await client.post("/mcp", json=INITIALIZE, headers={**ACCEPT, **_bearer(raw)})
    assert response.status_code == 500
    assert response.json() == {"detail": "errore interno"}


@pytest.mark.asyncio
async def test_a_build_that_fails_is_this_applications_own_500(
    served: tuple[McpHttpApp, httpx2.AsyncClient],
    root_token: tuple[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anything at all out of the build is one uniform 500 with a body.

    A pure ASGI application that lets an exception out sends no response at all, and the
    caller reads whatever the server invents -- a bodyless 500 under uvicorn.
    """
    raw, _ = root_token
    _, client = served

    async def esplode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("il build esplode")

    monkeypatch.setattr(McpHttpApp, "_build", esplode)
    response = await client.post("/mcp", json=INITIALIZE, headers={**ACCEPT, **_bearer(raw)})
    assert response.status_code == 500
    assert response.json() == {"detail": "errore interno"}


@pytest.mark.asyncio
async def test_a_domain_error_that_is_not_about_the_token_is_a_500_not_a_401(
    served: tuple[McpHttpApp, httpx2.AsyncClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only `validation_failed` means «this credential is no good».

    Every other `DomainError` reaching this boundary is a bug on our side, and telling
    the caller its token is invalid would send it to mint a second one that fails too.
    """
    _, client = served

    def conflitto(*args: Any, **kwargs: Any) -> Any:
        raise Conflict("token", "qualcosa di inatteso")

    monkeypatch.setattr(McpHttpApp, "_authenticate", conflitto)
    response = await client.post(
        "/mcp", json=INITIALIZE, headers={**ACCEPT, **_bearer("pgc_qualsiasi")}
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "errore interno"}


@pytest.mark.asyncio
async def test_the_bearer_scheme_is_read_case_insensitively(
    served: tuple[McpHttpApp, httpx2.AsyncClient], root_token: tuple[str, UUID]
) -> None:
    """`bearer` is the same scheme as `Bearer` (RFC 9110), and some clients send it."""
    raw, _ = root_token
    _, client = served
    response = await client.post(
        "/mcp", json=INITIALIZE, headers={**ACCEPT, "Authorization": f"bearer {raw}"}
    )
    assert response.status_code == 200


SPACES = ("spazio-uno", "spazio-due")


def _space_token(http_settings: Settings, slug: str) -> tuple[str, UUID]:
    """The admin the signup created, and a fresh PAT of theirs, on the space's database."""
    engine = create_engine(
        tenant_database_url(http_settings, tenant_database_name(slug)), future=True
    )
    try:
        with session_factory(engine)() as session:
            user = UserRepository(session).get_by_email(f"ada@{slug}.it")
            assert user is not None
            actor = Actor(id=user.id, type="user", role="admin")
            _, raw = PatService(session, settings=http_settings).create("prova", actor)
            session.commit()
            return raw, user.id
    finally:
        engine.dispose()


@pytest.fixture
def spaces(http_settings: Settings) -> Iterator[dict[str, tuple[str, UUID]]]:
    """Two real spaces on the container, each with an admin PAT; dropped afterwards."""
    registry = ensure_tenants_database(http_settings)
    tokens: dict[str, tuple[str, UUID]] = {}
    try:
        with session_factory(registry)() as session:
            for slug in SPACES:
                TenantService(session, http_settings).provision(
                    TenantSignup(
                        slug=slug, nome="Ada", email=f"ada@{slug}.it", password="lunghissima1"
                    )
                )
        for slug in SPACES:
            tokens[slug] = _space_token(http_settings, slug)
        yield tokens
    finally:
        with session_factory(registry)() as session:
            session.execute(text("delete from tenants where slug = any(:s)"), {"s": list(SPACES)})
            session.commit()
        registry.dispose()
        for slug in SPACES:
            drop_database(
                http_settings, tenant_database_url(http_settings, tenant_database_name(slug))
            )


@pytest.mark.asyncio
async def test_an_unknown_space_is_404_whatever_the_header_says(
    served: tuple[McpHttpApp, httpx2.AsyncClient],
) -> None:
    _, client = served
    response = await client.post(
        "/nessuno/mcp", json=INITIALIZE, headers={**ACCEPT, **_bearer("pgc_qualcosa")}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "spazio non trovato"}


@pytest.mark.asyncio
async def test_a_root_token_does_not_open_a_space(
    served: tuple[McpHttpApp, httpx2.AsyncClient],
    root_token: tuple[str, UUID],
    spaces: dict[str, tuple[str, UUID]],
) -> None:
    raw, _ = root_token
    _, client = served
    response = await client.post(
        "/spazio-uno/mcp", json=INITIALIZE, headers={**ACCEPT, **_bearer(raw)}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_space_token_opens_neither_the_root_nor_another_space(
    served: tuple[McpHttpApp, httpx2.AsyncClient], spaces: dict[str, tuple[str, UUID]]
) -> None:
    """The mirror of the test above: a token is a credential of one database only.

    The root and the other space each resolve it on their own `personal_access_tokens`,
    where its hash is not, so both answer the same 401 as an invented token.
    """
    uno = spaces["spazio-uno"][0]
    _, client = served
    for path in ["/mcp", "/spazio-due/mcp"]:
        response = await client.post(path, json=INITIALIZE, headers={**ACCEPT, **_bearer(uno)})
        assert response.status_code == 401, path
        assert response.json() == {"detail": "Token non valido"}


@pytest.mark.asyncio
async def test_two_spaces_do_not_see_each_other(
    served: tuple[McpHttpApp, httpx2.AsyncClient], spaces: dict[str, tuple[str, UUID]]
) -> None:
    app, _ = served
    uno, due = spaces["spazio-uno"][0], spaces["spazio-due"][0]
    await _call_tool(
        app,
        "http://prova/spazio-uno/mcp",
        uno,
        "create_customer",
        {"ragione_sociale": "Solo in uno"},
    )
    found_in_uno = await _call_tool(
        app, "http://prova/spazio-uno/mcp", uno, "search_customers", {"search": "Solo in uno"}
    )
    found_in_due = await _call_tool(
        app, "http://prova/spazio-due/mcp", due, "search_customers", {"search": "Solo in uno"}
    )
    assert len(found_in_uno["items"]) == 1
    assert len(found_in_due["items"]) == 0


@pytest.mark.asyncio
async def test_the_space_setting_decides_the_privileged_tools_and_a_change_rebuilds_the_server(
    served: tuple[McpHttpApp, httpx2.AsyncClient],
    spaces: dict[str, tuple[str, UUID]],
    http_settings: Settings,
) -> None:
    app, _ = served
    raw, user_id = spaces["spazio-uno"]
    url = "http://prova/spazio-uno/mcp"
    assert "issue_invoice" not in await _tool_names(app, url, raw)

    engine = create_engine(
        tenant_database_url(http_settings, tenant_database_name("spazio-uno")), future=True
    )
    try:
        with session_factory(engine)() as session:
            SpaceSettingsService(session, http_settings).update(
                SpaceSettingsUpdate(mcp_full_access=True),
                Actor(id=user_id, type="user", role="admin"),
                spazio="spazio-uno",
            )
            session.commit()
    finally:
        engine.dispose()

    # `overrides_ttl=0.0` in the `served` fixture: the next request re-reads the rows,
    # sees they changed, and rebuilds this space's server with the privileged tools.
    assert "issue_invoice" in await _tool_names(app, url, raw)
    # The other space is untouched.
    assert "issue_invoice" not in await _tool_names(
        app, "http://prova/spazio-due/mcp", spaces["spazio-due"][0]
    )
