# MCP over HTTP and «Collega un agente» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the existing MCP server over Streamable HTTP at `/<slug>/mcp`, authenticated with the existing personal access tokens, and give the sidebar a «Collega un agente» button whose dialog hands a client everything it needs to connect.

**Architecture:** A new `mcp` compose service runs `pigrocrm_mcp.http:app`, a pure ASGI application that strips the space prefix, verifies the bearer PAT on the space's database, and dispatches to one lazily built `MCPServer` per space (stateless Streamable HTTP, JSON responses). The pieces the API and the MCP now share (`split_tenant_prefix`, the engine-per-space registry, the per-space base settings) move into `pigrocrm.core.tenants`. The web app gets a dialog that shows the endpoint, mints a token and renders two copyable snippets.

**Tech Stack:** Python 3.13, `mcp==2.0.0` (Streamable HTTP, `ServerMiddleware`), Starlette/uvicorn (dependencies of the SDK), SQLAlchemy, FastAPI (API side only), pytest + testcontainers + `httpx2.ASGITransport`; React 19, TanStack Router/Query, shadcn/ui, vitest; docker compose, nginx.

**Spec:** `projects/pigrocrm/docs/superpowers/specs/2026-09-12-mcp-over-http-and-connect-an-agent-design.md`

## Global Constraints

- Everything committed is in English, except what the product says to its users, which is Italian: UI copy, error bodies (`{"detail": "Token non valido"}`, `{"detail": "spazio non trovato"}`), tool descriptions. (`AGENTS.md` root, «Everything in this repository is written in English».)
- Conventional Commits, English, first person, no em dashes, no emoji, **never an AI co-author trailer**. Reference the card as `Refs ORB-170` in the body.
- `packages/core` imports neither adapter; `apps/mcp` never imports `pigrocrm_api`; `apps/api` never imports `pigrocrm_mcp`. Enforced by `ruff.toml` banned-api and `packages/core/tests/test_architecture.py`.
- No new runtime dependency and no `uv.lock` change: `starlette`, `uvicorn` and `httpx2` are dependencies of `mcp==2.0.0` and are already locked. `httpx2`, not `httpx`, is what `mcp.client.streamable_http.streamable_http_client` accepts.
- No new environment variable. The `mcp` service reuses the `api` service's environment block verbatim.
- Product strings fixed by the spec: sidebar entry «Collega un agente»; dialog title «Collega un agente»; token name default «Claude Code»; server name in snippets `pigrocrm` for the root and `pigrocrm-<slug>` for a space.
- All commands below run from the worktree root `~/emdash/repositories/pigrocrm/.claude/worktrees/orb-170-mcp-http` unless a `cd` says otherwise. Python: `uv run --no-sync ...`. Web: `pnpm --filter web ...`.
- Docker is required for the Python tests (testcontainers). Run the Postgres suites one checkout at a time (`AGENTS.md` of the project).

---

## File map

**Create**
- `projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/prefix.py` — `split_tenant_prefix(path, root_slug, segments)`.
- `projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/registry.py` — `SpaceRegistry`, `space_base_settings`.
- `projects/pigrocrm/packages/core/tests/test_space_registry.py`.
- `projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/actor_scope.py` — `RequestActorProvider`, `ActorFromRequest`.
- `projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/http.py` — `create_app`, `McpHttpApp`.
- `projects/pigrocrm/apps/mcp/tests/test_actor_scope.py`, `test_http_transport.py`.
- `projects/pigrocrm/apps/web/src/features/tokens/useUnsavedTokenGuard.ts`.
- `projects/pigrocrm/apps/web/src/features/tokens/connectSnippets.ts` + `connectSnippets.test.ts`.
- `projects/pigrocrm/apps/web/src/features/tokens/ConnectAgentDialog.tsx` + `ConnectAgentDialog.test.tsx`.

**Modify**
- `packages/core/src/pigrocrm/core/tenants/{schemas.py,__init__.py}` — `mcp` reserved, exports.
- `packages/core/tests/test_tenants.py` — prefix tests.
- `apps/api/src/pigrocrm_api/{tenancy.py,deps.py}` — delegate to core.
- `apps/mcp/src/pigrocrm_mcp/server.py` — `middleware` parameter on `build_server`.
- `docker-compose.yml`, `deploy/nginx/spa.conf`.
- `apps/web/src/lib/tenant.ts` + `tenant.test.ts`, `apps/web/src/features/tokens/TokensPanel.tsx`, `apps/web/src/components/AppShell.tsx` + `AppShell.test.tsx`.
- `README.md`, `AGENTS.md` (project), `.env.example`, `docs/design/DECISIONS.md` (root), the spec's §9.

---

### Task 1: `split_tenant_prefix` moves to core and `mcp` becomes a reserved slug

**Files:**
- Create: `projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/prefix.py`
- Modify: `projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/schemas.py:18-36` (RESERVED_SLUGS)
- Modify: `projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/__init__.py`
- Modify: `projects/pigrocrm/apps/api/src/pigrocrm_api/tenancy.py` (remove the local definition, re-export from core)
- Modify: `projects/pigrocrm/apps/web/src/lib/tenant.ts` (RESERVED_SLUGS)
- Test: `projects/pigrocrm/packages/core/tests/test_tenants.py`, `projects/pigrocrm/apps/web/src/lib/tenant.test.ts`

**Interfaces:**
- Produces: `pigrocrm.core.tenants.prefix.split_tenant_prefix(path: str, root_slug: str = "", segments: tuple[str, ...] = API_SEGMENTS) -> tuple[str | None, str]`; constants `API_SEGMENTS = ("api", "health")`, `MCP_SEGMENTS = ("mcp",)`. Re-exported from `pigrocrm.core.tenants`.
- Consumed by Task 2 (deps), Task 4 (http.py).

- [ ] **Step 1: Write the failing core tests**

Append to `projects/pigrocrm/packages/core/tests/test_tenants.py` (add `from pigrocrm.core.tenants.prefix import API_SEGMENTS, MCP_SEGMENTS, split_tenant_prefix` to the imports):

```python
def test_the_prefix_splitter_recognises_the_api_segments_by_default() -> None:
    assert split_tenant_prefix("/studio/api/customers") == ("studio", "/api/customers")
    assert split_tenant_prefix("/studio/health") == ("studio", "/health")
    assert split_tenant_prefix("/api/customers") == (None, "/api/customers")
    assert split_tenant_prefix("/app/api/x") == (None, "/app/api/x")  # reserved word
    assert split_tenant_prefix("/studio/app/login") == (None, "/studio/app/login")
    assert split_tenant_prefix("/Studio/api/x") == (None, "/Studio/api/x")  # not a slug
    assert API_SEGMENTS == ("api", "health")


def test_the_prefix_splitter_serves_the_mcp_segment_when_asked() -> None:
    assert split_tenant_prefix("/studio/mcp", segments=MCP_SEGMENTS) == ("studio", "/mcp")
    assert split_tenant_prefix("/studio/mcp/", segments=MCP_SEGMENTS) == ("studio", "/mcp/")
    assert split_tenant_prefix("/mcp", segments=MCP_SEGMENTS) == (None, "/mcp")
    # The MCP splitter does not know the API's segments, and vice versa.
    assert split_tenant_prefix("/studio/api/x", segments=MCP_SEGMENTS) == (None, "/studio/api/x")
    assert split_tenant_prefix("/studio/mcp") == (None, "/studio/mcp")


def test_the_root_slug_is_stripped_but_stays_the_root_for_every_segment_set() -> None:
    assert split_tenant_prefix("/studiorossi/api/auth/me", "studiorossi") == (None, "/api/auth/me")
    assert split_tenant_prefix("/studiorossi/mcp", "studiorossi", MCP_SEGMENTS) == (None, "/mcp")
    assert split_tenant_prefix("/altro/mcp", "studiorossi", MCP_SEGMENTS) == ("altro", "/mcp")


def test_mcp_is_a_reserved_name() -> None:
    assert "mcp" in RESERVED_SLUGS
    assert validate_slug("mcp") == "questo nome è riservato"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --no-sync pytest -q projects/pigrocrm/packages/core/tests/test_tenants.py -k "prefix or reserved_name" -p no:cacheprovider`
Expected: FAIL, `ImportError: cannot import name 'API_SEGMENTS'` (the whole module fails to import; that is the failing state).

- [ ] **Step 3: Create `prefix.py`**

`projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/prefix.py`:

```python
"""Which space a request belongs to, read from the first segment of its path.

`/<slug>/api/...` and `/<slug>/health` are a space's requests to the API;
`/<slug>/mcp` is a space's request to the MCP server. Both adapters strip the prefix so
that their routes know nothing about tenants, and both apply the same three rules: a
reserved word is not a slug, a malformed segment is not a slug, and the root
installation's own name (`PIGROCRM_ROOT_SLUG`) is stripped like a space's but stays the
root. One function, parametrised on the segments an adapter serves, so the two cannot
drift -- this used to live in `apps/api/tenancy.py` alone.
"""

import re
from functools import lru_cache

from pigrocrm.core.tenants.schemas import RESERVED_SLUGS, SLUG_PATTERN

API_SEGMENTS: tuple[str, ...] = ("api", "health")
MCP_SEGMENTS: tuple[str, ...] = ("mcp",)


@lru_cache(maxsize=8)
def _pattern(segments: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(segment) for segment in segments)
    return re.compile(rf"^/([a-z0-9][a-z0-9-]{{1,30}}[a-z0-9])(/(?:{alternatives})(?:/.*)?)$")


def split_tenant_prefix(
    path: str, root_slug: str = "", segments: tuple[str, ...] = API_SEGMENTS
) -> tuple[str | None, str]:
    """`("studio", "/api/customers")` for `/studio/api/customers`; `(None, path)` when
    there is no prefix, or when the would-be slug is a reserved word -- `/api/...` is
    never anybody's space, and `/app/...` never reaches either adapter.

    `root_slug` is the root installation's own name: its prefix is stripped like a
    space's, but the request stays the root's -- `(None, rest)` -- so it opens the root
    database with the root's settings, Gmail and Drive included."""
    match = _pattern(segments).match(path)
    if not match:
        return None, path
    slug, rest = match.group(1), match.group(2)
    if root_slug and slug == root_slug:
        return None, rest
    if slug in RESERVED_SLUGS or not SLUG_PATTERN.match(slug):
        return None, path
    return slug, rest
```

- [ ] **Step 4: Reserve `mcp` and export the splitter**

In `schemas.py`, add `"mcp",` to the `RESERVED_SLUGS` frozenset (after `"registrati",`). In `tenants/__init__.py`, add:

```python
from pigrocrm.core.tenants.prefix import API_SEGMENTS, MCP_SEGMENTS, split_tenant_prefix
```

and `"API_SEGMENTS"`, `"MCP_SEGMENTS"`, `"split_tenant_prefix"` to `__all__` (keep the list sorted as it is).

- [ ] **Step 5: Make the API import it from core**

In `projects/pigrocrm/apps/api/src/pigrocrm_api/tenancy.py`: delete `_PREFIXED` and the whole `def split_tenant_prefix(...)` body; replace with

```python
from pigrocrm.core.tenants.prefix import split_tenant_prefix as split_tenant_prefix
```

(the `as` form is ruff's explicit re-export idiom; `apps/api/tests/test_tenants_api.py` keeps importing it from `pigrocrm_api.tenancy`). Remove the now-unused `import re` and the `RESERVED_SLUGS, SLUG_PATTERN` import if nothing else in the file uses them (`cookie_path` and friends do not). Update the module docstring's first paragraph to say the rule lives in `pigrocrm.core.tenants.prefix`.

- [ ] **Step 6: Run the core, API and architecture tests**

Run: `uv run --no-sync pytest -q projects/pigrocrm/packages/core/tests/test_tenants.py projects/pigrocrm/packages/core/tests/test_architecture.py projects/pigrocrm/apps/api/tests/test_tenants_api.py -p no:cacheprovider`
Expected: PASS. (`test_malformed_and_reserved_slugs_are_refused_with_a_reason` is parametrised over `sorted(RESERVED_SLUGS)`, so `mcp` is covered there too.)

- [ ] **Step 7: Mirror the reserved word in the SPA**

In `projects/pigrocrm/apps/web/src/lib/tenant.ts` add `'mcp',` to `RESERVED_SLUGS` (after `'registrati',`). In `tenant.test.ts`, inside `it('never mistakes a reserved word or a malformed segment for a space'` add:

```ts
    expect(tenantPrefixFrom('/mcp/app/login')).toBe('')
```

and inside `it('refuses short, malformed and reserved names with a reason'`:

```ts
    expect(slugProblem('mcp')).toMatch(/riservato/)
```

Run: `pnpm --filter web test -- src/lib/tenant.test.ts`
Expected: PASS.

- [ ] **Step 8: Lint and commit**

Run: `uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm && pnpm --filter web lint`
Expected: clean.

```bash
git add projects/pigrocrm/packages/core/src/pigrocrm/core/tenants projects/pigrocrm/packages/core/tests/test_tenants.py projects/pigrocrm/apps/api/src/pigrocrm_api/tenancy.py projects/pigrocrm/apps/web/src/lib/tenant.ts projects/pigrocrm/apps/web/src/lib/tenant.test.ts
git commit -m "refactor(pigrocrm): the space prefix rule lives in core, and mcp is a reserved name

split_tenant_prefix moves from apps/api to pigrocrm.core.tenants.prefix and takes
the segments it serves as a parameter, so the MCP server can apply the same rule
to /<slug>/mcp without importing the API. mcp joins the reserved slugs on both
sides, so no space can shadow the root endpoint.

Refs ORB-170"
```

---

### Task 2: `SpaceRegistry` in core, `deps.py` delegates

**Files:**
- Create: `projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/registry.py`
- Modify: `projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/__init__.py`
- Modify: `projects/pigrocrm/apps/api/src/pigrocrm_api/deps.py:27-135, 228-266`
- Test: `projects/pigrocrm/packages/core/tests/test_space_registry.py`

**Interfaces:**
- Produces:
  ```python
  def space_base_settings(settings: Settings, slug: str | None) -> Settings
  class SpaceRegistry:
      def __init__(self, settings: Settings, *, overrides_ttl: float = 10.0) -> None
      settings: Settings                                   # the settings it was built from
      def session_factory(self, slug: str | None) -> sessionmaker[Session]   # None = root; raises NotFound for an unknown slug
      def registry_factory(self) -> sessionmaker[Session]  # the tenants registry database
      def overrides(self, slug: str | None, session: Session) -> dict[str, str]
      def effective_settings(self, slug: str | None, session: Session) -> Settings
      def invalidate(self, slug: str | None) -> None
      def dispose(self) -> None
  ```
- Consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

`projects/pigrocrm/packages/core/tests/test_space_registry.py`:

```python
"""The engine-per-space registry both adapters share (ORB-170).

Real databases on the test container, as `test_tenants.py` does: the point of the
registry is which database a slug opens, which a savepoint session cannot express.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.db.sidecar import drop_database
from pigrocrm.core.errors import NotFound
from pigrocrm.core.space_settings import SpaceSettingsService, SpaceSettingsUpdate
from pigrocrm.core.tenants import (
    SpaceRegistry,
    TenantService,
    TenantSignup,
    ensure_tenants_database,
    space_base_settings,
)
from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url

SLUG = "registro-prova"


@pytest.fixture(scope="module")
def settings(db_engine: Engine) -> Settings:
    return Settings(
        database_url=db_engine.url.render_as_string(hide_password=False),
        public_url="https://pigro.example",
        google_client_id="root-client.apps",
        google_client_secret="root-secret",
        google_token_key="cm9vdC1rZXktMzItYnl0ZXMtbG9uZy1lbm91Z2gtLS0=",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def provisioned(settings: Settings) -> Iterator[str]:
    registry = ensure_tenants_database(settings)
    with session_factory(registry)() as session:
        TenantService(session, settings).provision(
            TenantSignup(slug=SLUG, nome="Ada", email="ada@studio.it", password="lunghissima1")
        )
    try:
        yield SLUG
    finally:
        with session_factory(registry)() as session:
            session.execute(text("delete from tenants where slug = :s"), {"s": SLUG})
            session.commit()
        drop_database(settings, tenant_database_url(settings, tenant_database_name(SLUG)))
        registry.dispose()


def test_the_root_has_no_slug_and_opens_the_configured_database(settings: Settings) -> None:
    registry = SpaceRegistry(settings)
    try:
        with registry.session_factory(None)() as session:
            db = session.execute(text("select current_database()")).scalar_one()
        assert db == settings.database_url.rsplit("/", 1)[1]
    finally:
        registry.dispose()


def test_an_unknown_slug_is_not_found(settings: Settings) -> None:
    registry = SpaceRegistry(settings)
    try:
        with pytest.raises(NotFound):
            registry.session_factory("nessuno-spazio")
    finally:
        registry.dispose()


def test_a_provisioned_slug_opens_its_own_database_once(settings: Settings, provisioned: str) -> None:
    registry = SpaceRegistry(settings)
    try:
        factory = registry.session_factory(provisioned)
        assert registry.session_factory(provisioned) is factory  # built once, then kept
        with factory() as session:
            db = session.execute(text("select current_database()")).scalar_one()
        assert db == tenant_database_name(provisioned)
    finally:
        registry.dispose()


def test_space_base_settings_blank_google_and_scope_the_public_url(settings: Settings) -> None:
    space = space_base_settings(settings, "studio")
    assert space.google_client_id == ""
    assert space.google_client_secret == ""
    assert space.google_token_key == ""
    assert space.public_url == "https://pigro.example/studio"
    assert space.storage_backend == "local"
    assert space_base_settings(settings, None) is settings


def test_overrides_are_cached_for_the_ttl_and_dropped_on_invalidate(
    settings: Settings, provisioned: str
) -> None:
    registry = SpaceRegistry(settings, overrides_ttl=1000.0)
    try:
        with registry.session_factory(provisioned)() as session:
            assert registry.overrides(provisioned, session) == {}
            admin = Actor(id=None, type="system", role="admin")
            SpaceSettingsService(session, registry.settings).update(
                SpaceSettingsUpdate(mcp_full_access=True), admin, spazio=provisioned
            )
            session.commit()
            # Still the cached answer: the TTL has not run out.
            assert registry.overrides(provisioned, session) == {}
            assert registry.effective_settings(provisioned, session).mcp_full_access is False
            registry.invalidate(provisioned)
            assert registry.overrides(provisioned, session) == {"mcp_full_access": "true"}
            assert registry.effective_settings(provisioned, session).mcp_full_access is True
    finally:
        registry.dispose()


def test_a_zero_ttl_reads_the_rows_every_time(settings: Settings, provisioned: str) -> None:
    registry = SpaceRegistry(settings, overrides_ttl=0.0)
    try:
        with registry.session_factory(provisioned)() as session:
            assert registry.overrides(provisioned, session) == {}
            admin = Actor(id=None, type="system", role="admin")
            SpaceSettingsService(session, registry.settings).update(
                SpaceSettingsUpdate(mcp_full_access=True), admin, spazio=provisioned
            )
            session.commit()
            assert registry.overrides(provisioned, session) == {"mcp_full_access": "true"}
    finally:
        registry.dispose()
```

Note on `SpaceSettingsService.update`: it calls `actor.require_admin(...)`; `Actor(id=None, type="system", role="admin")` passes that check (the same shape `Actor.system()` builds). Read `pigrocrm/core/actor.py` if the constructor refuses it and use `Actor.system()` instead.

- [ ] **Step 2: Run to see them fail**

Run: `uv run --no-sync pytest -q projects/pigrocrm/packages/core/tests/test_space_registry.py -p no:cacheprovider`
Expected: FAIL at import, `cannot import name 'SpaceRegistry'`.

- [ ] **Step 3: Write `registry.py`**

`projects/pigrocrm/packages/core/src/pigrocrm/core/tenants/registry.py`:

```python
"""One engine per space per process, and the settings each space sees.

Lifted out of `apps/api/deps.py` (ORB-170) because the MCP server over HTTP needs the
same three answers the API needs on every request: which database a slug opens, what
the space's base settings are (no root Google, a scoped public URL, documents on disk),
and which `space_settings` rows lay over them. Both adapters hold one instance of this
class per process and ask it; neither reimplements the caching.
"""

import threading
import time

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from pigrocrm.core.config import Settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.space_settings import SpaceSettingsService, apply_overrides
from pigrocrm.core.tenants.database import ensure_tenants_database, tenant_database_url
from pigrocrm.core.tenants.service import TenantService

OVERRIDES_TTL_SECONDS = 10.0
_ROOT = ""


def space_base_settings(settings: Settings, slug: str | None) -> Settings:
    """The environment's settings as a space may see them, before its database has its
    say. A space does not inherit the root's Google: the client, its secret and the
    token key are blanked, so a space either configures its own (Impostazioni → Spazio)
    or has no Gmail and no Drive. Its public URL is the root's plus the slug, which is
    where Google will redirect to, and documents default to disk under the space's own
    folder. The root sees the environment untouched, and gets the very same object."""
    if slug is None:
        return settings
    public_url = f"{settings.public_url.rstrip('/')}/{slug}" if settings.public_url else ""
    return settings.model_copy(
        update={
            "google_client_id": "",
            "google_client_secret": "",
            "google_token_key": "",
            "public_url": public_url,
            "google_app_unverified": False,
            "storage_backend": "local",
        }
    )


class SpaceRegistry:
    """Engines built on first use and kept; the tenants registry opened the same way.

    The lock is re-entrant, and it has to be: building a space's engine holds it while
    it asks the registry, and the registry's own first build takes the same lock. A
    plain `Lock` deadlocks the first request a space ever receives (found the hard
    way in `deps.py`, with a test suite that never finished).

    Overrides are cached for `overrides_ttl` seconds per slug: every request asks for
    its settings, and a read of a one-row table on each of them is cheap but not free.
    `invalidate` after a write, so the page that just saved sees what it saved.
    """

    def __init__(self, settings: Settings, *, overrides_ttl: float = OVERRIDES_TTL_SECONDS) -> None:
        self.settings = settings
        self._overrides_ttl = overrides_ttl
        self._lock = threading.RLock()
        self._root: sessionmaker[Session] | None = None
        self._registry: sessionmaker[Session] | None = None
        self._spaces: dict[str, sessionmaker[Session]] = {}
        self._overrides: dict[str, tuple[float, dict[str, str]]] = {}

    def registry_factory(self) -> sessionmaker[Session]:
        if self._registry is None:
            with self._lock:
                if self._registry is None:
                    self._registry = session_factory(ensure_tenants_database(self.settings))
        return self._registry

    def session_factory(self, slug: str | None) -> sessionmaker[Session]:
        if slug is None:
            if self._root is None:
                with self._lock:
                    if self._root is None:
                        self._root = session_factory(create_engine_from_settings(self.settings))
            return self._root
        factory = self._spaces.get(slug)
        if factory is None:
            with self._lock:
                factory = self._spaces.get(slug)
                if factory is None:
                    registry = self.registry_factory()()
                    try:
                        # `NotFound` for a slug nobody registered: a wrong address, not a
                        # server fault. Callers turn it into their own 404.
                        tenant = TenantService(registry, self.settings).get(slug)
                    finally:
                        registry.close()
                    engine = create_engine(
                        tenant_database_url(self.settings, tenant.db_name),
                        pool_pre_ping=True,
                        future=True,
                    )
                    factory = session_factory(engine)
                    self._spaces[slug] = factory
        return factory

    def overrides(self, slug: str | None, session: Session) -> dict[str, str]:
        key = slug or _ROOT
        cached = self._overrides.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._overrides_ttl:
            return cached[1]
        rows = SpaceSettingsService(session, space_base_settings(self.settings, slug)).overrides()
        self._overrides[key] = (now, rows)
        return rows

    def effective_settings(self, slug: str | None, session: Session) -> Settings:
        return apply_overrides(space_base_settings(self.settings, slug), self.overrides(slug, session))

    def invalidate(self, slug: str | None) -> None:
        self._overrides.pop(slug or _ROOT, None)

    def dispose(self) -> None:
        with self._lock:
            for factory in [self._root, self._registry, *self._spaces.values()]:
                if factory is None:
                    continue
                bind = factory.kw.get("bind")
                if isinstance(bind, Engine):
                    bind.dispose()
            self._root = None
            self._registry = None
            self._spaces.clear()
            self._overrides.clear()
```

Export from `tenants/__init__.py`: `from pigrocrm.core.tenants.registry import OVERRIDES_TTL_SECONDS, SpaceRegistry, space_base_settings` and the three names in `__all__`.

Check for an import cycle: `registry.py` imports `space_settings`, which imports `activities`; none of those import `tenants`. If `test_architecture.py` complains about an import not declared, nothing new is imported from outside core here.

- [ ] **Step 4: Run the registry tests**

Run: `uv run --no-sync pytest -q projects/pigrocrm/packages/core/tests/test_space_registry.py -p no:cacheprovider`
Expected: PASS (6 tests).

- [ ] **Step 5: Make `deps.py` delegate**

In `projects/pigrocrm/apps/api/src/pigrocrm_api/deps.py`:

1. Replace the imports `from pigrocrm.core.tenants import TenantService, ensure_tenants_database` and `from pigrocrm.core.tenants.database import tenant_database_url` with `from pigrocrm.core.tenants import SpaceRegistry, space_base_settings`. Drop `create_engine`, `Engine`, `create_engine_from_settings`, `session_factory`, `time`, `SpaceSettingsService` from the imports if they become unused (ruff will say). Keep `apply_overrides` only if still used (it is not after step 5.4).

2. Replace everything from `_engine: Engine | None = None` down to the end of `reset_tenant_caches()` (the root engine, `reset_session_factories`, `_tenant_factories`, `_tenants_registry`, `_tenants_lock`, `_registry_factory`, `get_tenants_registry_session`, `TenantsRegistryDep`, `_tenant_session_factory`, `_factory_for`, `reset_tenant_caches`) with:

```python
# One registry per process (spec 2026-09-08, lifted to core in ORB-170): the root's
# engine, every space's engine and the tenants registry, all built on first use from the
# first caller's settings. Callers with a request pass the settings dependency through,
# so a test's override of `get_settings` decides the server; callers without one
# (`_fresh_session`) get the process settings, which in production are the same object.
_registry: SpaceRegistry | None = None
_registry_lock = threading.Lock()


def _space_registry(settings: Settings | None = None) -> SpaceRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:  # a concurrent caller may have just finished building it
                _registry = SpaceRegistry(settings or get_settings())
    return _registry


def _get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    return _space_registry(settings).session_factory(None)


def reset_session_factories() -> None:
    """Forgets the root's engine along with every space's and the registry, for a test
    that points the whole process at another server through `get_settings`."""
    global _registry
    with _registry_lock:
        if _registry is not None:
            _registry.dispose()
        _registry = None


def get_tenants_registry_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[Session]:
    """A session on the registry database -- the list of spaces, never a space."""
    session = _space_registry(settings).registry_factory()()
    try:
        yield session
    finally:
        session.close()


TenantsRegistryDep = Annotated[Session, Depends(get_tenants_registry_session)]


def _tenant_session_factory(slug: str, settings: Settings) -> sessionmaker[Session]:
    return _space_registry(settings).session_factory(slug)


def _factory_for(request: Request, settings: Settings) -> sessionmaker[Session]:
    slug = tenant_slug(request)
    return _tenant_session_factory(slug, settings) if slug else _get_session_factory(settings)
```

3. In `request_base_settings`, replace the body after the docstring with `return space_base_settings(settings, tenant_slug(request))`.

4. Replace `_overrides_cache`, `OVERRIDES_TTL_SECONDS`, `_space_overrides` and the body of `invalidate_space_settings`/`get_request_settings` with:

```python
def invalidate_space_settings(slug: str | None) -> None:
    """After a write to `space_settings`: forget the cached rows and the storage built
    from them, for this database only."""
    _space_registry().invalidate(slug)
    if slug is None:
        reset_storage_cache()
    else:
        with _storage_lock:
            _tenant_storages.pop(slug, None)


def get_request_settings(
    request: Request,
    base: BaseSettingsDep,
    session: Annotated[Session, Depends(get_session)],
) -> Settings:
    """The settings every route reads: the environment as this request may see it,
    with the rows of this database's `space_settings` laid over it. The session is the
    request's own (FastAPI caches the dependency), so a test's override of
    `get_session` is where the rows come from too."""
    return apply_overrides(base, _space_registry(base).overrides(tenant_slug(request), session))
```

`base` here is already the space's base settings, and `SpaceRegistry.overrides` reads the rows through `SpaceSettingsService(session, ...)`, which only needs a session: the `base` it receives internally is used by nothing in `.overrides()`. Keep `apply_overrides` imported.

Search the file for any other reference to the deleted names (`grep -n "_tenant_factories\|_tenants_registry\|_overrides_cache\|_engine\b\|_factory\b" deps.py`) and fix each: `get_storage` calls `_tenant_session_factory(slug, settings)`, which still exists.

- [ ] **Step 6: Run the API suite parts that touch spaces, settings and storage**

Run: `uv run --no-sync pytest -q projects/pigrocrm/apps/api/tests/test_tenants_api.py projects/pigrocrm/apps/api/tests/test_space_settings_api.py projects/pigrocrm/apps/api/tests/test_documents_api.py projects/pigrocrm/apps/api/tests/test_drive_api.py -p no:cacheprovider`
Expected: PASS. If a test imports a deleted private name from `deps`, that test is wrong about the module's shape now: point it at `reset_session_factories()`.

Then the whole API suite once: `uv run --no-sync pytest -q -n auto --dist loadfile -m "not slow and not planner" projects/pigrocrm/apps/api/tests -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm`

```bash
git add projects/pigrocrm/packages/core/src/pigrocrm/core/tenants projects/pigrocrm/packages/core/tests/test_space_registry.py projects/pigrocrm/apps/api/src/pigrocrm_api/deps.py
git commit -m "refactor(pigrocrm): the engine-per-space registry lives in core

SpaceRegistry holds the root's engine, every space's engine, the tenants
registry and the ten-second cache of space_settings rows, and
space_base_settings is what a space sees before its database has its say.
deps.py keeps its names and delegates. No behaviour changes; the API suite
is the guard. The MCP server over HTTP needs the same answers on every request.

Refs ORB-170"
```

---

### Task 3: the actor travels with the request

**Files:**
- Create: `projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/actor_scope.py`
- Modify: `projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/server.py:54-58, 111` (`middleware` parameter)
- Test: `projects/pigrocrm/apps/mcp/tests/test_actor_scope.py`

**Interfaces:**
- Produces:
  ```python
  class RequestActorProvider:           # ActorProvider
      def __call__(self) -> Actor       # RuntimeError outside a request
  class ActorFromRequest:               # mcp.server.context.ServerMiddleware
      async def __call__(self, ctx, call_next) -> HandlerResult
  build_server(session_provider, actor_provider, storage=None, settings=None, *, middleware=None)
  ```
- Consumed by Task 4.

- [ ] **Step 1: Write the failing test**

`projects/pigrocrm/apps/mcp/tests/test_actor_scope.py`:

```python
"""The actor of an HTTP request reaches the tool through a ContextVar (ORB-170).

Verified in-process against the installed SDK, not assumed: under stateless Streamable
HTTP a `ServerMiddleware` receives the Starlette `Request` as `ctx.request`, and a
`ContextVar` set there is visible to the tool function `call_next` reaches (the SDK
dispatches the call inside the same task tree). This test is what pins that.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from pigrocrm.core.actor import Actor
from pigrocrm_mcp.actor_scope import ActorFromRequest, RequestActorProvider

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

ADA = Actor(id=None, type="mcp", role="collaboratore")


def _server(provider: RequestActorProvider) -> MCPServer:
    mcp = MCPServer("prova", middleware=[ActorFromRequest()])

    @mcp.tool()
    def chi_sono() -> str:
        actor = provider()
        return f"{actor.type}:{actor.role}"

    return mcp


def _stamping(inner: Any, actor: Actor | None) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and actor is not None:
            scope.setdefault("state", {})["actor"] = actor
        await inner(scope, receive, send)

    return app


async def _call(app: Any, starlette_app: Any) -> str:
    async with starlette_app.router.lifespan_context(starlette_app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://prova") as client:
            async with streamable_http_client("http://prova/mcp", http_client=client) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("chi_sono", {})
                    return result.content[0].text  # type: ignore[union-attr]


def _http_app(mcp: MCPServer) -> Any:
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


@pytest.mark.asyncio
async def test_the_actor_stamped_on_the_request_is_what_the_tool_sees() -> None:
    provider = RequestActorProvider()
    starlette = _http_app(_server(provider))
    assert await _call(_stamping(starlette, ADA), starlette) == "mcp:collaboratore"


@pytest.mark.asyncio
async def test_a_request_without_an_actor_is_refused_before_the_tool_runs() -> None:
    provider = RequestActorProvider()
    starlette = _http_app(_server(provider))
    with pytest.raises(Exception, match="nessun attore"):
        await _call(_stamping(starlette, None), starlette)


def test_the_provider_refuses_outside_a_request() -> None:
    with pytest.raises(RuntimeError, match="no request actor is bound"):
        RequestActorProvider()()
```

`pyproject.toml` sets `asyncio_mode = "auto"`, so the `@pytest.mark.asyncio` markers are redundant but harmless; they document intent.

- [ ] **Step 2: Run to see it fail**

Run: `uv run --no-sync pytest -q projects/pigrocrm/apps/mcp/tests/test_actor_scope.py -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'pigrocrm_mcp.actor_scope'`.

- [ ] **Step 3: Write `actor_scope.py`**

```python
"""Who is calling, over HTTP: one actor per request, carried on a ContextVar.

Over stdio the actor is resolved once at start-up and never changes (`__main__.py`).
Over HTTP every request carries its own bearer token, so the actor is resolved per
request by `pigrocrm_mcp.http` and stamped on the ASGI scope; `ActorFromRequest` is
the SDK's context-tier middleware that copies it from `ctx.request.state` into a
`ContextVar` for the duration of the call, and `RequestActorProvider` is the
`ActorProvider` `build_server` reads it back through. A `ContextVar`, like
`ScopedSessionProvider`'s session, because the SDK dispatches tools both on the event
loop and in a thread pool, and a `ContextVar` is the one primitive correct for both.
"""

import contextvars
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError

from pigrocrm.core.actor import Actor

_CURRENT_ACTOR: contextvars.ContextVar[Actor] = contextvars.ContextVar("mcp_request_actor")

ACTOR_STATE_KEY = "actor"


class RequestActorProvider:
    """`ActorProvider` for the HTTP transport: the actor bound to the current call."""

    def __call__(self) -> Actor:
        try:
            return _CURRENT_ACTOR.get()
        except LookupError as exc:
            raise RuntimeError(
                "no request actor is bound: every tool and resource over HTTP must run "
                "inside ActorFromRequest"
            ) from exc


class ActorFromRequest:
    """`ServerMiddleware`: binds the request's actor for the handler, then unbinds it.

    Refuses a request that carries no actor instead of letting the tool run as nobody:
    the ASGI layer stamps one on every authenticated request, so its absence is a
    programming error, and the message is the product's, because it is what a client
    would show.
    """

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        request = ctx.request
        actor = getattr(getattr(request, "state", None), ACTOR_STATE_KEY, None)
        if not isinstance(actor, Actor):
            raise MCPError(code=-32001, message="nessun attore associato alla richiesta")
        token = _CURRENT_ACTOR.set(actor)
        try:
            return await call_next(ctx)
        finally:
            _CURRENT_ACTOR.reset(token)
```

`MCPError` is `mcp.shared.exceptions.MCPError` in `mcp==2.0.0` (checked).

- [ ] **Step 4: Add `middleware` to `build_server`**

In `server.py`, change the signature to:

```python
def build_server(
    session_provider: SessionProvider,
    actor_provider: ActorProvider,
    storage: DocumentStorage | None = None,
    settings: Settings | None = None,
    *,
    middleware: Sequence[ServerMiddleware[Any]] | None = None,
) -> MCPServer:
```

with `from collections.abc import Callable, Sequence` and `from mcp.server.context import ServerMiddleware` added to the imports, and the construction line becomes
`mcp = MCPServer("PigroCRM", instructions=INSTRUCTIONS, middleware=middleware)`. Add to the docstring comment block above: "`middleware` is the SDK's context-tier hook, used by the HTTP transport to bind the request's actor (`actor_scope.py`); stdio passes none."

- [ ] **Step 5: Run the test**

Run: `uv run --no-sync pytest -q projects/pigrocrm/apps/mcp/tests/test_actor_scope.py -p no:cacheprovider`
Expected: PASS (3 tests). If the second test's error text does not surface through the client as an exception whose message contains «nessun attore», print the raised exception once, and match on whatever the client actually raises (`McpError`/`MCPError` with the message), then keep the assertion on the message.

- [ ] **Step 6: Commit**

```bash
git add projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/actor_scope.py projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/server.py projects/pigrocrm/apps/mcp/tests/test_actor_scope.py
git commit -m "feat(pigrocrm-mcp): the actor of an HTTP request reaches the tools through a ContextVar

A ServerMiddleware copies the actor the ASGI layer stamped on the request into a
ContextVar for the duration of the call, and RequestActorProvider is the
ActorProvider build_server reads it through. build_server accepts the middleware
list; stdio passes none and is unchanged.

Refs ORB-170"
```

---

### Task 4: `pigrocrm_mcp.http` — the ASGI application, root only

**Files:**
- Create: `projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/http.py`
- Test: `projects/pigrocrm/apps/mcp/tests/test_http_transport.py` (root cases; Task 5 adds spaces)

**Interfaces:**
- Consumes: `SpaceRegistry`, `space_base_settings`, `split_tenant_prefix`, `MCP_SEGMENTS` (Tasks 1–2); `RequestActorProvider`, `ActorFromRequest`, `build_server(..., middleware=)` (Task 3).
- Produces:
  ```python
  class McpHttpApp:                     # ASGI callable, handles "lifespan" and "http"
      def __init__(self, settings: Settings, *, overrides_ttl: float = OVERRIDES_TTL_SECONDS) -> None
      def lifespan(self) -> AbstractAsyncContextManager[None]   # for tests without a server
      async def __call__(self, scope, receive, send) -> None
  def create_app(settings: Settings | None = None, *, overrides_ttl: float = OVERRIDES_TTL_SECONDS) -> McpHttpApp
  app = create_app()   # module level, for `uvicorn pigrocrm_mcp.http:app`
  ```

Design points the implementer must respect (they are why the module looks the way it does):

- **Inner lifespans.** The Starlette app the SDK returns has a lifespan that starts its `StreamableHTTPSessionManager`; without it every request fails with «Task group is not initialized». Space apps are built lazily, inside a request, so their lifespan cannot be entered from the outer ASGI lifespan directly. `McpHttpApp.lifespan()` therefore opens one `anyio` task group that lives for the whole process; building a space app spawns a task in that group which enters the inner lifespan and waits on a stop event, and the builder waits on a started event before returning. Shutdown sets every stop event and exits the group. Entering and exiting anyio scopes from different tasks is exactly what this avoids.
- **Blocking work off the loop.** `PatService.resolve` and the registry lookups are synchronous SQLAlchemy calls: run them via `anyio.to_thread.run_sync`.
- **Order of checks:** prefix → the stripped path must be exactly `/mcp` (else 404 «non trovato») → the slug must exist (else 404 «spazio non trovato») → bearer PAT (else 401 «Token non valido» + `WWW-Authenticate: Bearer`) → space app (rebuilt if the overrides changed) → dispatch with `scope["state"]["actor"]`.
- **The module-level `app`** is built with `get_settings()` at import time, like `pigrocrm_api.main:app`. It must not open any connection at import: `SpaceRegistry` is lazy, and so is everything else here.

- [ ] **Step 1: Write the failing root tests**

`projects/pigrocrm/apps/mcp/tests/test_http_transport.py`:

```python
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
            UserCreate(email=EMAIL, password="lunghissima1", nome="Trasporto", ruolo="collaboratore"),
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
            session.execute(delete(PersonalAccessToken).where(PersonalAccessToken.user_id == user_id))
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
    async with _authed(app, token) as authed:
        async with streamable_http_client(url, http_client=authed) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                return sorted(tool.name for tool in (await session.list_tools()).tools)


async def _call_tool(
    app: McpHttpApp, url: str, token: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    async with _authed(app, token) as authed:
        async with streamable_http_client(url, http_client=authed) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
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
```

Verify the imports the fixtures lean on before running: `UserCreate` lives in `pigrocrm.core.auth.schemas` and `UserService.create(data, actor)` returns the `User` (used by `TenantService.provision`, see `tenants/service.py`); `PatService.list(actor)`/`revoke(token_id, actor)` (see `pat_service.py`). `Activity` is `pigrocrm.core.activities.models.Activity`. The `create_customer` tool answers the customer's own JSON dump, so `created["id"]` is the new id (`tools/customers.py:9-11`).

- [ ] **Step 2: Run to see them fail**

Run: `uv run --no-sync pytest -q projects/pigrocrm/apps/mcp/tests/test_http_transport.py -p no:cacheprovider`
Expected: FAIL at import, `No module named 'pigrocrm_mcp.http'`.

- [ ] **Step 3: Write `http.py`**

```python
"""The MCP server over Streamable HTTP, one endpoint per space (ORB-170).

`/<slug>/mcp` and `/mcp` (the root), served by the `mcp` compose service behind the
web container's nginx. A pure ASGI application rather than a Starlette one, because it
has to rewrite the path *before* routing and stamp the actor on the scope, exactly as
`pigrocrm_api.tenancy.TenantPrefixMiddleware` does for the API -- and because the SDK's
own Starlette app, one per space, is what it dispatches to.

The three answers every request needs come from `SpaceRegistry` (which database, what
the space's settings are, which rows lay over them); the credential is a personal
access token as a bearer, resolved by `PatService.resolve` on the space's database with
the space's settings applied, so `Actor.full_access` is the space's answer. Everything
is lazy: importing this module opens nothing, and a space's server is built on its
first request and rebuilt when its settings rows change.

Why one `MCPServer` per space: `build_server` registers tools according to the settings
it receives (`mcp_full_access`, whether Google is configured), so a process serving
several spaces cannot share one tool list.

Why an anyio task group of its own: the Starlette app the SDK returns has a lifespan
that starts its session manager, without which every request fails. Space apps are
built inside a request, so their lifespan is entered by a task spawned in a group this
application opens once for the whole process, and left when the process stops --
anyio does not allow entering a scope in one task and leaving it in another.
"""

import json
from collections.abc import Awaitable, Callable, MutableMapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from anyio.abc import TaskGroup
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.pat_service import PAT_PREFIX, PatService
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.errors import DomainError, ValidationFailed
from pigrocrm.core.storage import DocumentStorage, LocalFileStorage, storage_from_settings
from pigrocrm.core.tenants import (
    OVERRIDES_TTL_SECONDS,
    MCP_SEGMENTS,
    SpaceRegistry,
    split_tenant_prefix,
)
from pigrocrm_mcp.actor_scope import ACTOR_STATE_KEY, ActorFromRequest, RequestActorProvider
from pigrocrm_mcp.context import ScopedSessionProvider
from pigrocrm_mcp.server import build_server

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

MCP_PATH = "/mcp"
HEALTH_PATH = "/health"
_ROOT = ""

# The API's wording, so a client sees the same words whichever door it knocked on.
INVALID_TOKEN = "Token non valido"
SPACE_NOT_FOUND = "spazio non trovato"
NOT_FOUND = "non trovato"


@dataclass
class _SpaceApp:
    app: ASGIApp
    overrides: dict[str, str]
    stop: anyio.Event


@dataclass(frozen=True)
class _Authenticated:
    actor: Actor
    overrides: dict[str, str]
    settings: Settings


class McpHttpApp:
    def __init__(self, settings: Settings, *, overrides_ttl: float = OVERRIDES_TTL_SECONDS) -> None:
        self._settings = settings
        self._registry = SpaceRegistry(settings, overrides_ttl=overrides_ttl)
        self._spaces: dict[str, _SpaceApp] = {}
        self._build_lock = anyio.Lock()
        self._task_group: TaskGroup | None = None

    # -- lifespan --------------------------------------------------------------------

    @asynccontextmanager
    async def _run(self) -> Any:
        async with anyio.create_task_group() as task_group:
            self._task_group = task_group
            try:
                yield
            finally:
                for space in self._spaces.values():
                    space.stop.set()
                self._spaces.clear()
                self._task_group = None
        self._registry.dispose()

    def lifespan(self) -> AbstractAsyncContextManager[None]:
        """For a test that drives the app through `httpx2.ASGITransport`, which does not
        speak the lifespan protocol. A server (uvicorn) goes through `__call__`."""
        return self._run()

    async def _lifespan_protocol(self, receive: Receive, send: Send) -> None:
        message = await receive()
        assert message["type"] == "lifespan.startup"
        async with self._run():
            await send({"type": "lifespan.startup.complete"})
            message = await receive()
            assert message["type"] == "lifespan.shutdown"
        await send({"type": "lifespan.shutdown.complete"})

    # -- the request -----------------------------------------------------------------

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan_protocol(receive, send)
            return
        if scope["type"] != "http":
            return

        path: str = scope["path"]
        if path == HEALTH_PATH:
            await _json(send, 200, {"status": "ok"})
            return

        slug, rest = split_tenant_prefix(path, self._settings.root_slug, MCP_SEGMENTS)
        if rest.rstrip("/") != MCP_PATH:
            await _json(send, 404, {"detail": NOT_FOUND})
            return

        try:
            auth = await anyio.to_thread.run_sync(self._authenticate, slug, _bearer_of(scope))
        except DomainError as exc:
            if exc.code == "not_found":
                await _json(send, 404, {"detail": SPACE_NOT_FOUND})
            else:
                await _json(send, 401, {"detail": INVALID_TOKEN}, {"www-authenticate": "Bearer"})
            return

        space = await self._space_app(slug, auth)
        scope["path"] = MCP_PATH
        scope["raw_path"] = MCP_PATH.encode("utf-8")
        scope.setdefault("state", {})[ACTOR_STATE_KEY] = auth.actor
        await space.app(scope, receive, send)

    def _authenticate(self, slug: str | None, raw_token: str | None) -> _Authenticated:
        """Synchronous, run in a worker thread: two reads on the space's database.

        The slug is resolved first, so an unknown space is 404 whatever the header says,
        the way the API answers. Then the settings rows, so the token is resolved with
        the space's `mcp_full_access`, not the environment's. Any failure of the token
        itself is the same `ValidationFailed`, which the caller turns into one 401.
        """
        factory = self._registry.session_factory(slug)  # NotFound for an unknown slug
        with factory() as session:
            overrides = self._registry.overrides(slug, session)
            settings = self._registry.effective_settings(slug, session)
            if not raw_token:
                # The same class `PatService.resolve` raises, so the caller has one branch.
                raise ValidationFailed("token", "token", INVALID_TOKEN)
            actor = PatService(session, settings=settings).resolve(raw_token)
            session.commit()  # `resolve` stamps last_used_at
        return _Authenticated(actor=actor, overrides=overrides, settings=settings)

    async def _space_app(self, slug: str | None, auth: _Authenticated) -> _SpaceApp:
        key = slug or _ROOT
        current = self._spaces.get(key)
        if current is not None and current.overrides == auth.overrides:
            return current
        async with self._build_lock:
            current = self._spaces.get(key)
            if current is not None and current.overrides == auth.overrides:
                return current
            if current is not None:
                current.stop.set()  # the settings changed: this server's tool list is stale
            built = await self._build(slug, auth)
            self._spaces[key] = built
            return built

    async def _build(self, slug: str | None, auth: _Authenticated) -> _SpaceApp:
        if self._task_group is None:
            raise RuntimeError("McpHttpApp is not running: enter its lifespan first")
        provider = ScopedSessionProvider(self._registry.session_factory(slug))
        storage = _storage_for(slug, auth.settings, provider)
        server = build_server(
            provider,
            RequestActorProvider(),
            storage,
            auth.settings,
            middleware=[ActorFromRequest()],
        )
        starlette = server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            json_response=True,
            # Behind nginx the Host header is the public domain, which differs between
            # the root, the preview and every self-hosted installation; the service has
            # no host port, so nginx is what binds the name. Off is the honest setting.
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        started = anyio.Event()
        stop = anyio.Event()

        async def serve() -> None:
            async with starlette.router.lifespan_context(starlette):
                started.set()
                await stop.wait()

        self._task_group.start_soon(serve)
        await started.wait()
        return _SpaceApp(app=starlette, overrides=auth.overrides, stop=stop)


def _storage_for(
    slug: str | None, settings: Settings, provider: ScopedSessionProvider
) -> DocumentStorage | None:
    """A space's documents live on disk under its own folder, or on its own Drive when
    its settings say so -- the same two arms `pigrocrm_api.deps.get_storage` has. The
    root returns None and lets `build_server` do what `__main__.py` does."""
    if slug is None:
        return None
    if settings.storage_backend == "gdrive":
        return storage_from_settings(settings, session_factory=provider.new_session)
    return LocalFileStorage(Path(settings.storage_local_root) / "tenants" / slug)


def _bearer_of(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            header = value.decode("latin-1")
            if header.startswith("Bearer ") and header[7:].startswith(PAT_PREFIX):
                return header[7:]
            return None
    return None


async def _json(
    send: Send, status: int, body: dict[str, Any], extra_headers: dict[str, str] | None = None
) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(payload)).encode("ascii")),
    ]
    for name, value in (extra_headers or {}).items():
        headers.append((name.encode("latin-1"), value.encode("latin-1")))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


def create_app(
    settings: Settings | None = None, *, overrides_ttl: float = OVERRIDES_TTL_SECONDS
) -> McpHttpApp:
    return McpHttpApp(settings or get_settings(), overrides_ttl=overrides_ttl)


app = create_app()
```

`exc.code == "not_found"` is what `TenantService.get` raises through `SpaceRegistry.session_factory`; every other `DomainError` here comes from the token and is the 401.

- [ ] **Step 4: Run the root tests**

Run: `uv run --no-sync pytest -q projects/pigrocrm/apps/mcp/tests/test_http_transport.py -p no:cacheprovider`
Expected: PASS (8 tests). Likely first failures and their fixes:
- «Task group is not initialized»: the inner lifespan did not start before the first dispatch; make sure `_build` awaits `started`.
- The 404 test for `/mcpx`: `split_tenant_prefix` returns `(None, "/mcpx")`, whose `rstrip("/")` is not `/mcp`; correct as written.

- [ ] **Step 5: Lint, format, commit**

Run: `uv run ruff check projects/pigrocrm && uv run ruff format projects/pigrocrm && uv run ruff format --check projects/pigrocrm`

```bash
git add projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/http.py projects/pigrocrm/apps/mcp/tests/test_http_transport.py
git commit -m "feat(pigrocrm-mcp): the MCP server speaks Streamable HTTP behind a bearer PAT

pigrocrm_mcp.http is a pure ASGI application: it strips the space prefix, resolves
the personal access token on the space's database with the space's settings
applied, and dispatches to one lazily built MCPServer per space, stateless and
answering JSON. Missing or wrong tokens are one uniform 401; a path that is not
/mcp is 404. Space servers live in a task group the app opens once, so their
lifespans are entered and left in the same task.

Refs ORB-170"
```

---

### Task 5: spaces over HTTP

**Files:**
- Test: `projects/pigrocrm/apps/mcp/tests/test_http_transport.py` (append)
- Modify (only if a test forces it): `projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/http.py`

**Interfaces:** consumes Task 4 as is.

- [ ] **Step 1: Write the failing space tests**

Append to `test_http_transport.py` (add the imports `from sqlalchemy import text`, `from pigrocrm.core.db.sidecar import drop_database`, `from pigrocrm.core.space_settings import SpaceSettingsService, SpaceSettingsUpdate`, `from pigrocrm.core.tenants import TenantService, TenantSignup, ensure_tenants_database`, `from pigrocrm.core.tenants.database import tenant_database_name, tenant_database_url`, `from pigrocrm.core.auth.repository import UserRepository`, `from sqlalchemy import create_engine`):

```python
SPACES = ("spazio-uno", "spazio-due")


def _space_token(http_settings: Settings, slug: str) -> tuple[str, UUID]:
    """The admin the signup created, and a fresh PAT of theirs, on the space's database."""
    engine = create_engine(tenant_database_url(http_settings, tenant_database_name(slug)), future=True)
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
                    TenantSignup(slug=slug, nome="Ada", email=f"ada@{slug}.it", password="lunghissima1")
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
            drop_database(http_settings, tenant_database_url(http_settings, tenant_database_name(slug)))


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
    response = await client.post("/spazio-uno/mcp", json=INITIALIZE, headers={**ACCEPT, **_bearer(raw)})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_two_spaces_do_not_see_each_other(
    served: tuple[McpHttpApp, httpx2.AsyncClient], spaces: dict[str, tuple[str, UUID]]
) -> None:
    app, _ = served
    uno, due = spaces["spazio-uno"][0], spaces["spazio-due"][0]
    await _call_tool(app, "http://prova/spazio-uno/mcp", uno, "create_customer", {"ragione_sociale": "Solo in uno"})
    found_in_uno = await _call_tool(app, "http://prova/spazio-uno/mcp", uno, "search_customers", {"search": "Solo in uno"})
    found_in_due = await _call_tool(app, "http://prova/spazio-due/mcp", due, "search_customers", {"search": "Solo in uno"})
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
    assert "issue_invoice" not in await _tool_names(app, "http://prova/spazio-due/mcp", spaces["spazio-due"][0])
```

`search_customers` takes `search` and answers `{"items": [...], ...}` (`tools/__init__.py:246`, `tools/customers.py:28`).

- [ ] **Step 2: Run to see the new tests fail or pass**

Run: `uv run --no-sync pytest -q projects/pigrocrm/apps/mcp/tests/test_http_transport.py -p no:cacheprovider`
Expected: the four new tests exercise Task 4's code without new production code; they should PASS. If `test_the_space_setting_decides...` fails on the second `_tool_names`, the rebuild path in `_space_app` is broken: confirm `auth.overrides` differs from `current.overrides` (`{"mcp_full_access": "true"}` vs `{}`) and that `_build` is reached.

- [ ] **Step 3: Run the whole MCP suite and the architecture test**

Run: `uv run --no-sync pytest -q -n auto --dist loadfile projects/pigrocrm/apps/mcp/tests projects/pigrocrm/packages/core/tests/test_architecture.py -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add projects/pigrocrm/apps/mcp/tests/test_http_transport.py projects/pigrocrm/apps/mcp/src/pigrocrm_mcp/http.py
git commit -m "test(pigrocrm-mcp): spaces over HTTP are separate, and a setting change rebuilds the server

Refs ORB-170"
```

---

### Task 6: the `mcp` compose service and the nginx route

**Files:**
- Modify: `projects/pigrocrm/docker-compose.yml:1-13` (head comment), `:43-96` (api environment into an anchor), new `mcp` service
- Modify: `projects/pigrocrm/deploy/nginx/spa.conf`

**Interfaces:** the service name `mcp` on port `8001` is what `spa.conf` proxies to.

- [ ] **Step 1: Rewrite the head comment of `docker-compose.yml`**

Replace lines 1–13 with:

```yaml
# apps/mcp speaks two transports. Over stdio (`python -m pigrocrm_mcp`, see its
# __main__.py) it is launched as a subprocess by an MCP client that owns its
# stdin/stdout for one session -- there is no service for that here, and an operator
# who wants it runs it on demand inside the api image, with a personal access token
# from Impostazioni -> Token in the UI:
#   docker compose run --rm -e PIGROCRM_TOKEN=<token> api uv run --no-sync python -m pigrocrm_mcp
# Over Streamable HTTP (`pigrocrm_mcp.http`, ORB-170) it is the `mcp` service below:
# the same image as `api`, the same environment and the same documents volume,
# reached only through the `web` container's nginx at /<slug>/mcp and /mcp, with the
# same tokens as bearers. It has no host port on purpose.
```

- [ ] **Step 2: Lift the api environment into an anchor and add the service**

Immediately after the `services:` line is not valid for anchors; put a top-level extension block **before** `services:`:

```yaml
x-api-environment: &api-environment
  PIGROCRM_DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-pigrocrm}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-pigrocrm}
  PIGROCRM_JWT_SECRET: ${PIGROCRM_JWT_SECRET:?serve un secret}
  ... (move every key of the api service's `environment:` block here, comments included, verbatim)
```

Then in the `api` service replace the whole `environment:` mapping with `environment: *api-environment`, keeping the long comment about `PIGROCRM_COOKIE_SECURE` where it is (it explains an absence, which is still true for both services). Add after the `api` service:

```yaml
  mcp:
    build:
      context: ../..
      dockerfile: projects/pigrocrm/Dockerfile.api
    restart: unless-stopped
    # After `api`, which runs the migrations at start-up; this process never migrates
    # and must not touch a database that is still being upgraded.
    depends_on:
      db:
        condition: service_healthy
      api:
        condition: service_started
    environment: *api-environment
    command: ["uv", "run", "--no-sync", "uvicorn", "pigrocrm_mcp.http:app", "--host", "0.0.0.0", "--port", "8001"]
    volumes:
      - ${PIGROCRM_DOCUMENTS_DIR:-../../var/documents}:/app/var/documents
```

Run: `cd projects/pigrocrm && POSTGRES_PASSWORD=x PIGROCRM_JWT_SECRET=build-only-and-long-enough-for-the-validator docker compose config --services`
Expected: `db`, `api`, `mcp`, `web`. Then `docker compose config | grep -c PIGROCRM_MCP_FULL_ACCESS` prints `2` (once per service).

- [ ] **Step 3: Route `/mcp` and `/<slug>/mcp` in `spa.conf`**

Add after the `(api|health)` regex block:

```nginx
    # The MCP server over HTTP (ORB-170): /<slug>/mcp and, below, /mcp for the root, to
    # the `mcp` service. Same variable-upstream reasoning as the API blocks. JSON
    # request/response, but buffering is off and the read timeout is long because the
    # transport may also answer with an event stream.
    location ~ "^/[a-z0-9][a-z0-9-]{1,30}[a-z0-9]/mcp(/|$)" {
        set $mcp_upstream http://mcp:8001;
        proxy_pass $mcp_upstream$request_uri;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 300s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
```

and, next to `location = /health`:

```nginx
    location = /mcp {
        set $mcp_upstream http://mcp:8001;
        proxy_pass $mcp_upstream$request_uri;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 300s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
```

Note the regex `location ~ "^/([a-z0-9][a-z0-9-]{1,30}[a-z0-9])$"` (bare slug → redirect) does not match `/mcp`? It does: `mcp` is a well-formed slug. The exact-match `location = /mcp` wins over any regex in nginx, so the redirect never fires for it. Keep the exact-match block.

- [ ] **Step 4: Build both images and check the nginx syntax**

Run from `projects/pigrocrm`:
```bash
POSTGRES_PASSWORD=x PIGROCRM_JWT_SECRET=build-only-and-long-enough-for-the-validator docker compose build mcp web
docker run --rm --entrypoint nginx pigrocrm-web -t
```
Expected: the build succeeds; `nginx -t` prints `syntax is ok` and `test is successful`. (`pigrocrm-web` is the tag compose gives the `web` service's image from the directory name; `docker compose build web` prints it.)

- [ ] **Step 5: Smoke the stack locally on private ports**

From `projects/pigrocrm`, with a scratch data dir so nothing lands in the repository:
```bash
export SCRATCH=/private/tmp/orb170-compose && mkdir -p $SCRATCH/pg $SCRATCH/docs
POSTGRES_PASSWORD=orb170 PIGROCRM_JWT_SECRET=orb170-secret-long-enough-for-the-validator-yes \
PIGROCRM_WEB_PORT=127.0.0.1:18080 PIGROCRM_DB_PORT=127.0.0.1:55499 \
PIGROCRM_DATA_DIR=$SCRATCH/pg PIGROCRM_DOCUMENTS_DIR=$SCRATCH/docs \
docker compose -p orb170 up -d
sleep 20
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/health          # 200
curl -s -i http://127.0.0.1:18080/mcp -X POST -H 'Content-Type: application/json' -d '{}' | head -5   # 401, WWW-Authenticate: Bearer, {"detail":"Token non valido"}
curl -s -i http://127.0.0.1:18080/nessuno/mcp -X POST -d '{}' | head -3          # 404 spazio non trovato
docker compose -p orb170 logs mcp | tail -5                                      # uvicorn running on 8001
docker compose -p orb170 down -v
```
Expected: the codes in the comments. The 401 from outside is the health check the spec names.

- [ ] **Step 6: Commit**

```bash
git add projects/pigrocrm/docker-compose.yml projects/pigrocrm/deploy/nginx/spa.conf
git commit -m "feat(pigrocrm): an mcp compose service behind nginx at /<slug>/mcp

Same image, environment and documents volume as api, no host port; the web
container's nginx forwards /<slug>/mcp and /mcp to it. The head comment now
explains both transports instead of the absence of a service.

Refs ORB-170"
```

---

### Task 7: `useUnsavedTokenGuard` is shared

**Files:**
- Create: `projects/pigrocrm/apps/web/src/features/tokens/useUnsavedTokenGuard.ts`
- Modify: `projects/pigrocrm/apps/web/src/features/tokens/TokensPanel.tsx:1-4, 54-56, 68-77`
- Test: `projects/pigrocrm/apps/web/src/features/tokens/TokensPanel.test.tsx` (existing, must stay green)

**Interfaces:**
- Produces: `export const LEAVE_WARNING: string`; `export function useUnsavedTokenGuard(issued: boolean): void`; `export function confirmDiscardingToken(): boolean` (wraps `window.confirm(LEAVE_WARNING)`).

- [ ] **Step 1: Create the hook**

```ts
import { useBlocker } from '@tanstack/react-router'

/**
 * A freshly minted token is on screen exactly once. Leaving the page while it is there --
 * by a Link, by Back, by a reload or by closing the tab -- loses it for good, so every
 * surface that reveals one asks the same question first. Shared between the Token page
 * and the «Collega un agente» dialog so the two cannot drift.
 */
export const LEAVE_WARNING =
  'Il token mostrato non è stato confermato come copiato: se esci ora sparisce per sempre e dovrai revocarlo e crearne uno nuovo. Uscire comunque?'

export function confirmDiscardingToken(): boolean {
  return window.confirm(LEAVE_WARNING)
}

/** Escape and click-outside are the dialog's own business; this covers the two ways those
 *  do not: an in-app route change (`useBlocker`) and a real reload or close
 *  (`enableBeforeUnload`, the native "leave site?" prompt). Both can be declined. */
export function useUnsavedTokenGuard(issued: boolean): void {
  useBlocker({
    shouldBlockFn: () => issued && !confirmDiscardingToken(),
    enableBeforeUnload: issued,
  })
}
```

- [ ] **Step 2: Use it in `TokensPanel.tsx`**

Remove `import { useBlocker } from '@tanstack/react-router'` and the `LEAVE_WARNING` constant; add `import { useUnsavedTokenGuard } from './useUnsavedTokenGuard'`; replace the `useBlocker({...})` call and its comment with `useUnsavedTokenGuard(Boolean(issued))`. If the panel references `LEAVE_WARNING` anywhere else, import it from the hook module.

- [ ] **Step 3: Run the token tests**

Run: `pnpm --filter web test -- src/features/tokens`
Expected: PASS. The suite mocks `useBlocker` from `@tanstack/react-router`; the hook imports it from there, so `latestBlockerArgs()` still sees the calls.

- [ ] **Step 4: Commit**

```bash
git add projects/pigrocrm/apps/web/src/features/tokens/useUnsavedTokenGuard.ts projects/pigrocrm/apps/web/src/features/tokens/TokensPanel.tsx
git commit -m "refactor(pigrocrm-web): the unsaved-token guard is a hook the Token page shares

Refs ORB-170"
```

---

### Task 8: snippet builders

**Files:**
- Create: `projects/pigrocrm/apps/web/src/features/tokens/connectSnippets.ts`
- Test: `projects/pigrocrm/apps/web/src/features/tokens/connectSnippets.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export const TOKEN_PLACEHOLDER = '<token>'
  export function mcpEndpoint(origin: string, prefix: string): string          // `${origin}${prefix}/mcp`
  export function serverName(prefix: string): string                           // 'pigrocrm' | `pigrocrm-${slug}`
  export function claudeCodeCommand(name: string, url: string, token: string): string
  export function mcpServersJson(name: string, url: string, token: string): string
  ```

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import {
  TOKEN_PLACEHOLDER,
  claudeCodeCommand,
  mcpEndpoint,
  mcpServersJson,
  serverName,
} from './connectSnippets'

describe('the endpoint', () => {
  it('is the origin plus the space prefix plus /mcp', () => {
    expect(mcpEndpoint('https://pigro.example', '')).toBe('https://pigro.example/mcp')
    expect(mcpEndpoint('https://pigro.example', '/studio')).toBe('https://pigro.example/studio/mcp')
  })
})

describe('the server name', () => {
  it('is pigrocrm for the root and pigrocrm-<slug> for a space, so two spaces never collide', () => {
    expect(serverName('')).toBe('pigrocrm')
    expect(serverName('/studio')).toBe('pigrocrm-studio')
  })
})

describe('the snippets', () => {
  const url = 'https://pigro.example/studio/mcp'

  it('build the claude mcp add command with the bearer header', () => {
    expect(claudeCodeCommand('pigrocrm-studio', url, 'pgc_abc')).toBe(
      'claude mcp add --transport http pigrocrm-studio https://pigro.example/studio/mcp --header "Authorization: Bearer pgc_abc"',
    )
  })

  it('build a valid mcpServers JSON document', () => {
    const parsed = JSON.parse(mcpServersJson('pigrocrm-studio', url, 'pgc_abc'))
    expect(parsed).toEqual({
      mcpServers: {
        'pigrocrm-studio': {
          type: 'http',
          url,
          headers: { Authorization: 'Bearer pgc_abc' },
        },
      },
    })
  })

  it('carry the placeholder until a token exists', () => {
    expect(claudeCodeCommand('pigrocrm', url, TOKEN_PLACEHOLDER)).toContain('Bearer <token>')
    expect(mcpServersJson('pigrocrm', url, TOKEN_PLACEHOLDER)).toContain('Bearer <token>')
  })
})
```

- [ ] **Step 2: Run to see it fail**

Run: `pnpm --filter web test -- src/features/tokens/connectSnippets.test.ts`
Expected: FAIL, cannot resolve `./connectSnippets`.

- [ ] **Step 3: Write the module**

```ts
/**
 * What a client needs to connect to this installation's MCP server over HTTP (ORB-170):
 * the endpoint, a name for the server, and the two forms a configuration takes.
 * Pure functions, so the dialog's tests can look at strings.
 */
export const TOKEN_PLACEHOLDER = '<token>'

/** `https://host/mcp` for the root, `https://host/<slug>/mcp` for a space. */
export function mcpEndpoint(origin: string, prefix: string): string {
  return `${origin}${prefix}/mcp`
}

/** The name the client files the server under. A space gets its slug in the name, so a
 *  person with two spaces in one client does not end up with two `pigrocrm` entries. */
export function serverName(prefix: string): string {
  const slug = prefix.replace(/^\//, '')
  return slug ? `pigrocrm-${slug}` : 'pigrocrm'
}

export function claudeCodeCommand(name: string, url: string, token: string): string {
  return `claude mcp add --transport http ${name} ${url} --header "Authorization: Bearer ${token}"`
}

export function mcpServersJson(name: string, url: string, token: string): string {
  return JSON.stringify(
    { mcpServers: { [name]: { type: 'http', url, headers: { Authorization: `Bearer ${token}` } } } },
    null,
    2,
  )
}
```

- [ ] **Step 4: Run, then commit**

Run: `pnpm --filter web test -- src/features/tokens/connectSnippets.test.ts`
Expected: PASS.

```bash
git add projects/pigrocrm/apps/web/src/features/tokens/connectSnippets.ts projects/pigrocrm/apps/web/src/features/tokens/connectSnippets.test.ts
git commit -m "feat(pigrocrm-web): the snippets a client needs to connect to the MCP server

Refs ORB-170"
```

---

### Task 9: `ConnectAgentDialog`

**Files:**
- Create: `projects/pigrocrm/apps/web/src/features/tokens/ConnectAgentDialog.tsx`
- Test: `projects/pigrocrm/apps/web/src/features/tokens/ConnectAgentDialog.test.tsx`

**Interfaces:**
- Consumes: Task 7 hook, Task 8 builders, `useCreateToken`/`CreatedToken` from `./queries`, `tenantPrefix` from `@/lib/tenant`, `fieldErrorFrom`/`toProblem` from `@/lib/api`.
- Produces: `export function ConnectAgentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void })`.

- [ ] **Step 1: Write the failing test**

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ConnectAgentDialog } from './ConnectAgentDialog'
import { api } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn(), PATCH: vi.fn() } }
})
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useBlocker: vi.fn(),
    Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
  }
})
const mockTenant = vi.hoisted(() => ({ prefix: '' }))
vi.mock('@/lib/tenant', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/tenant')>()
  return {
    ...actual,
    get tenantPrefix() {
      return mockTenant.prefix
    },
  }
})

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function renderDialog(onOpenChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ConnectAgentDialog open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  return onOpenChange
}

beforeEach(() => {
  vi.mocked(api.POST).mockReset()
  mockTenant.prefix = ''
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

describe('ConnectAgentDialog', () => {
  it('shows the endpoint of this installation, built from the page origin and the space prefix', () => {
    mockTenant.prefix = '/studio'
    renderDialog()
    expect(screen.getByRole('dialog', { name: 'Collega un agente' })).toBeInTheDocument()
    expect(screen.getByLabelText('Endpoint')).toHaveValue(`${window.location.origin}/studio/mcp`)
  })

  it('carries a placeholder in both snippets until a token exists', () => {
    renderDialog()
    expect(screen.getByLabelText('Comando per Claude Code')).toHaveValue(
      expect.stringContaining('Bearer <token>'),
    )
    expect(screen.getByLabelText('Configurazione JSON')).toHaveValue(expect.stringContaining('Bearer <token>'))
    expect(screen.getByLabelText('Comando per Claude Code')).toHaveValue(
      expect.stringContaining(`claude mcp add --transport http pigrocrm ${window.location.origin}/mcp`),
    )
  })

  it('mints a token with the prefilled name and puts it in both snippets', async () => {
    vi.mocked(api.POST).mockReturnValueOnce(
      Promise.resolve(
        ok({
          id: 't2',
          nome: 'Claude Code',
          prefix: 'pgc_zzzz9999',
          last_used_at: null,
          revoked_at: null,
          created_at: '2026-09-12T10:00:00Z',
          token: 'pgc_il-valore-intero',
        }),
      ),
    )
    renderDialog()
    expect(screen.getByLabelText('Nome del token')).toHaveValue('Claude Code')
    await userEvent.click(screen.getByRole('button', { name: 'Crea il token' }))
    expect(await screen.findByDisplayValue('pgc_il-valore-intero')).toBeInTheDocument()
    expect(screen.getByLabelText('Comando per Claude Code')).toHaveValue(
      expect.stringContaining('Bearer pgc_il-valore-intero'),
    )
    expect(screen.getByLabelText('Configurazione JSON')).toHaveValue(
      expect.stringContaining('Bearer pgc_il-valore-intero'),
    )
    expect(vi.mocked(api.POST)).toHaveBeenCalledWith('/api/tokens', { body: { nome: 'Claude Code' } })
    // The name field and the button are gone: the token is minted exactly once per dialog.
    expect(screen.queryByRole('button', { name: 'Crea il token' })).not.toBeInTheDocument()
  })

  it('copies a snippet to the clipboard', async () => {
    renderDialog()
    await userEvent.click(screen.getByRole('button', { name: 'Copia il comando per Claude Code' }))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('claude mcp add'))
  })

  it('asks before closing while a token is on screen, and closes only on yes', async () => {
    vi.mocked(api.POST).mockReturnValueOnce(
      Promise.resolve(ok({ id: 't2', nome: 'Claude Code', prefix: 'pgc_zzzz9999', last_used_at: null, revoked_at: null, created_at: '2026-09-12T10:00:00Z', token: 'pgc_x' })),
    )
    const onOpenChange = renderDialog()
    await userEvent.click(screen.getByRole('button', { name: 'Crea il token' }))
    await screen.findByDisplayValue('pgc_x')
    vi.mocked(window.confirm).mockReturnValueOnce(false)
    await userEvent.click(screen.getByRole('button', { name: 'Chiudi' }))
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
    vi.mocked(window.confirm).mockReturnValueOnce(true)
    await userEvent.click(screen.getByRole('button', { name: 'Chiudi' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('links to the Token page', () => {
    renderDialog()
    expect(within(screen.getByRole('dialog')).getByRole('link', { name: 'Gestisci i token' })).toHaveAttribute(
      'href',
      '/app/token',
    )
  })
})
```

- [ ] **Step 2: Run to see it fail**

Run: `pnpm --filter web test -- src/features/tokens/ConnectAgentDialog.test.tsx`
Expected: FAIL, cannot resolve `./ConnectAgentDialog`.

- [ ] **Step 3: Write the component**

```tsx
import { Link } from '@tanstack/react-router'
import { Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { fieldErrorFrom, toProblem, type ProblemDetail } from '@/lib/api'
import { tenantPrefix } from '@/lib/tenant'
import {
  TOKEN_PLACEHOLDER,
  claudeCodeCommand,
  mcpEndpoint,
  mcpServersJson,
  serverName,
} from './connectSnippets'
import { useCreateToken, type CreatedToken } from './queries'
import { confirmDiscardingToken, useUnsavedTokenGuard } from './useUnsavedTokenGuard'

/**
 * Everything a client needs to talk to this installation's MCP server over HTTP
 * (ORB-170): the endpoint, a token minted right here, and the two shapes a
 * configuration takes. The token is shown once, like on the Token page, and the same
 * guard asks before it is lost. Opened from the sidebar's «Collega un agente».
 */
export function ConnectAgentDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [nome, setNome] = useState('Claude Code')
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [issued, setIssued] = useState<CreatedToken | null>(null)
  const create = useCreateToken()
  useUnsavedTokenGuard(Boolean(issued))

  const url = mcpEndpoint(window.location.origin, tenantPrefix)
  const name = serverName(tenantPrefix)
  const token = issued?.token ?? TOKEN_PLACEHOLDER
  const command = claudeCodeCommand(name, url, token)
  const json = mcpServersJson(name, url, token)
  const fieldError = problem ? fieldErrorFrom(problem) : null
  const banner = problem && fieldError?.field !== 'nome' ? problem.detail : null

  function close(next: boolean) {
    if (!next && issued && !confirmDiscardingToken()) return
    if (!next) {
      setIssued(null)
      setProblem(null)
      setNome('Claude Code')
    }
    onOpenChange(next)
  }

  function mint() {
    setProblem(null)
    create.mutate(nome, {
      onSuccess: (created) => setIssued(created),
      onError: (error) => setProblem(toProblem(error)),
    })
  }

  function copy(text: string, what: string) {
    void navigator.clipboard.writeText(text).then(() => toast.success(`${what} copiato negli appunti`))
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Collega un agente</DialogTitle>
          <DialogDescription>
            Un agente come Claude Code parla con PigroCRM tramite il server MCP, con un token
            di accesso di questo account. Copia l&apos;endpoint e uno dei due snippet.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <Field
            label="Endpoint"
            copyLabel="Copia l'endpoint"
            id="mcp-endpoint"
            value={url}
            onCopy={() => copy(url, "L'endpoint")}
          />

          {issued ? (
            <div className="space-y-2">
              <Label htmlFor="mcp-token">Token</Label>
              <div className="flex gap-2">
                <Input id="mcp-token" readOnly value={issued.token} className="font-mono text-xs" />
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="Copia il token"
                  onClick={() => copy(issued.token, 'Il token')}
                >
                  <Copy className="size-4" />
                </Button>
              </div>
              <p className="text-sm text-muted-foreground">
                Viene mostrato una volta sola. Eredita <strong>l&apos;intero ruolo di questo
                account</strong>, senza scadenza: trattalo come una password e revocalo dalla
                pagina Token se sospetti che sia stato esposto.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                Serve un token di accesso: viene mostrato una volta sola.
              </p>
              {banner && (
                <p
                  role="alert"
                  className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  {banner}
                </p>
              )}
              <Label htmlFor="mcp-token-nome">Nome del token</Label>
              <div className="flex gap-2">
                <Input
                  id="mcp-token-nome"
                  aria-invalid={fieldError?.field === 'nome'}
                  value={nome}
                  onChange={(event) => setNome(event.target.value)}
                />
                <Button onClick={mint} disabled={create.isPending}>
                  Crea il token
                </Button>
              </div>
              {fieldError?.field === 'nome' && (
                <p className="text-sm text-destructive">{fieldError.message}</p>
              )}
            </div>
          )}

          <Field
            label="Comando per Claude Code"
            copyLabel="Copia il comando per Claude Code"
            id="mcp-claude-code"
            value={command}
            onCopy={() => copy(command, 'Il comando')}
            multiline
          />
          <Field
            label="Configurazione JSON"
            copyLabel="Copia la configurazione JSON"
            id="mcp-json"
            value={json}
            onCopy={() => copy(json, 'La configurazione')}
            multiline
          />
        </div>

        <DialogFooter className="sm:justify-between">
          <Button variant="ghost" asChild>
            <Link to="/app/token">Gestisci i token</Link>
          </Button>
          <Button onClick={() => close(false)}>Chiudi</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** A read-only value with its copy button; `copyLabel` is the button's accessible name. */
function Field({
  label,
  copyLabel,
  id,
  value,
  onCopy,
  multiline = false,
}: {
  label: string
  copyLabel: string
  id: string
  value: string
  onCopy: () => void
  multiline?: boolean
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        {multiline ? (
          <Textarea id={id} readOnly value={value} rows={3} className="font-mono text-xs" />
        ) : (
          <Input id={id} readOnly value={value} className="font-mono text-xs" />
        )}
        <Button variant="outline" size="icon" aria-label={copyLabel} onClick={onCopy}>
          <Copy className="size-4" />
        </Button>
      </div>
    </div>
  )
}
```

`fieldErrorFrom` returns `{ field, message } | null` (`lib/api.ts:399`); `Textarea` is `@/components/ui/textarea`.

- [ ] **Step 4: Run the test, fix, run again**

Run: `pnpm --filter web test -- src/features/tokens/ConnectAgentDialog.test.tsx`
Expected: PASS (6 tests). If `toHaveValue(expect.stringContaining(...))` is not accepted on a textarea by the matcher version in use, read the value with `(screen.getByLabelText(...) as HTMLTextAreaElement).value` and `toContain`.

- [ ] **Step 5: Lint, typecheck, commit**

Run: `pnpm --filter web lint && pnpm --filter web exec tsc --noEmit`

```bash
git add projects/pigrocrm/apps/web/src/features/tokens/ConnectAgentDialog.tsx projects/pigrocrm/apps/web/src/features/tokens/ConnectAgentDialog.test.tsx
git commit -m "feat(pigrocrm-web): the «Collega un agente» dialog mints a token and hands over the snippets

Refs ORB-170"
```

---

### Task 10: the sidebar entry

**Files:**
- Modify: `projects/pigrocrm/apps/web/src/components/AppShell.tsx` (imports, state, the block between `</nav>` and the profile)
- Test: `projects/pigrocrm/apps/web/src/components/AppShell.test.tsx`

**Interfaces:** consumes `ConnectAgentDialog` (Task 9).

- [ ] **Step 1: Write the failing tests**

In `AppShell.test.tsx`, extend the `@tanstack/react-router` mock with `useBlocker: vi.fn(),` (the dialog's guard), and add `vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))` beside the other mocks. Then add:

```tsx
  it.each(['admin', 'collaboratore', 'readonly'])('offers «Collega un agente» to a %s, above the profile', (ruolo) => {
    mockAuth.ruolo = ruolo
    renderShell()
    const button = screen.getByRole('button', { name: 'Collega un agente' })
    expect(button).toBeInTheDocument()
    // Above the profile block: the button comes before the profile trigger in the DOM.
    const profile = screen.getByRole('button', { name: 'Menu del profilo' })
    expect(button.compareDocumentPosition(profile) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('opens the connect dialog from the sidebar', async () => {
    renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Collega un agente' }))
    expect(screen.getByRole('dialog', { name: 'Collega un agente' })).toBeInTheDocument()
  })

  it('keeps the entry in the rail as an icon with its name', async () => {
    renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Comprimi il menu' }))
    expect(screen.getByRole('button', { name: 'Collega un agente' })).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to see them fail**

Run: `pnpm --filter web test -- src/components/AppShell.test.tsx`
Expected: the three new tests FAIL (`Unable to find role="button" and name "Collega un agente"`).

- [ ] **Step 3: Add the entry**

In `AppShell.tsx`: add `Plug` to the lucide import list; add `import { ConnectAgentDialog } from '@/features/tokens/ConnectAgentDialog'`; add `const [agentOpen, setAgentOpen] = useState(false)` next to `searchOpen`. Between `</nav>` and the profile `<div className="mt-auto ...">` insert:

```tsx
        {/* «Collega un agente» (ORB-170): for every role, like Token, because a token
            belongs to whoever creates it. A button and not a route: the dialog is the
            whole surface. In the rail the label is for screen readers only. */}
        <div className="px-3 pb-1">
          <button
            type="button"
            onClick={() => setAgentOpen(true)}
            className={cn(ITEM, QUIET, FOCUS, 'w-full', rail && 'justify-center px-0')}
          >
            <Plug className="size-4 shrink-0" aria-hidden="true" />
            <span className={cn('truncate', rail && 'sr-only')}>Collega un agente</span>
          </button>
        </div>
        <ConnectAgentDialog open={agentOpen} onOpenChange={setAgentOpen} />
```

Note `mt-auto` on the profile block still pushes it to the bottom; the nav has `flex-1`, so the new block sits directly above the profile. If the nav's `flex-1` leaves no gap issue, nothing else changes.

- [ ] **Step 4: Run the shell tests and the whole web suite**

Run: `pnpm --filter web test`
Expected: PASS.

- [ ] **Step 5: Look at it**

Run the dev server (`pnpm --filter web dev` against a local API, or the e2e recipe in `apps/web/scripts/e2e.sh`) and open the app: the entry sits above the profile, expanded and in the rail; the dialog opens, shows the endpoint `http://localhost:5173/mcp`, the placeholder snippets, and the copy buttons work. If a screenshot is convenient, take one for the PR (the memory note «screenshot stack off :8000» has the recipe for a box where :8000 is busy).

- [ ] **Step 6: Lint, typecheck, commit**

Run: `pnpm --filter web lint && pnpm --filter web build`

```bash
git add projects/pigrocrm/apps/web/src/components/AppShell.tsx projects/pigrocrm/apps/web/src/components/AppShell.test.tsx
git commit -m "feat(pigrocrm-web): «Collega un agente» sits above the profile in the sidebar

Refs ORB-170"
```

---

### Task 11: documentation and the decision row

**Files:**
- Modify: `projects/pigrocrm/README.md` (new section after «## Deploy» steps, before «## Status»)
- Modify: `projects/pigrocrm/AGENTS.md:39`
- Modify: `projects/pigrocrm/.env.example:64-84` (one sentence)
- Modify: `docs/design/DECISIONS.md` (one row, newest last)
- Modify: the spec's §9

- [ ] **Step 1: README**

Insert before `## Status`:

````markdown
## Connect an agent

Every operation in the UI is also an MCP tool. Over HTTP the server answers at
`https://<host>/mcp` for the root installation and `https://<host>/<slug>/mcp` for a
space, authenticated with a personal access token as a bearer. In the app, the
«Collega un agente» entry at the bottom of the sidebar mints a token and gives you
both snippets below with the values filled in.

```
claude mcp add --transport http pigrocrm https://<host>/mcp --header "Authorization: Bearer pgc_..."
```

```json
{"mcpServers": {"pigrocrm": {"type": "http", "url": "https://<host>/mcp",
  "headers": {"Authorization": "Bearer pgc_..."}}}}
```

The token inherits the whole role of whoever created it; revoke it from Impostazioni →
Token if it leaks. Claude Code, Cursor, Codex and any client that can send a header
work; the connectors of claude.ai and Claude Desktop need OAuth, which this server does
not offer yet. The stdio transport is still there for a client that launches the server
itself (see the head of `docker-compose.yml`).
````

- [ ] **Step 2: AGENTS.md and .env.example**

`AGENTS.md` line 39 becomes `apps/mcp/        the MCP server, stdio and Streamable HTTP. Imports core.`

`.env.example`: after the sentence «It doesn't replace the role: a `readonly` user's token stays read-only.» add a paragraph:

```
# The same switch governs the HTTP transport (the `mcp` compose service): a token is
# resolved with the space's settings applied, so a space decides for itself in
# Impostazioni -> Spazio and the root decides here.
```

- [ ] **Step 3: DECISIONS.md**

Append one row (keep the four columns, one line):

```
| 2026-09-12 | Ivan asked for a sidebar button that connects an agent to the CRM's MCP server («un pulsante per far collegare verso il server mcp», ORB-170). The server spoke stdio only, launched over SSH inside the api container. How does a client reach it, and with what credential? | Streamable HTTP, stateless with JSON responses, served by an `mcp` compose service behind the web container's nginx at `/<slug>/mcp`, one `MCPServer` per space because the tool list depends on the space's settings. The credential is the existing personal access token as a bearer, resolved with the space's settings; no OAuth. The sidebar button opens a dialog that mints a token and hands over the `claude mcp add` command and the `mcpServers` JSON. | An adapter that needs the space rule or the engine-per-space registry takes them from `pigrocrm.core.tenants` (`split_tenant_prefix`, `SpaceRegistry`), never from the other adapter. The PAT is the one agent credential on both transports, and what it may do is the space's `mcp_full_access`, never the process environment's. OAuth is deferred until a client that requires it (claude.ai, Claude Desktop) is in scope; the ASGI wrapper in `pigrocrm_mcp.http` is where its verifier goes. |
```

- [ ] **Step 4: Spec §9**

In the spec, replace the sentence «Two things the implementation plan verifies before anything else, because ... exercised:» and item 1 with a short paragraph: «Retired on 2026-09-12 before the plan was written: an in-process spike confirmed that under stateless Streamable HTTP a `ServerMiddleware` receives the Starlette `Request` as `ctx.request` and that a `ContextVar` set there reaches the tool; `apps/mcp/tests/test_actor_scope.py` pins it.» Keep item 2 (Claude Code end to end) as the remaining verification, done in Task 12.

- [ ] **Step 5: Commit**

```bash
git add projects/pigrocrm/README.md projects/pigrocrm/AGENTS.md projects/pigrocrm/.env.example docs/design/DECISIONS.md projects/pigrocrm/docs/superpowers/specs/2026-09-12-mcp-over-http-and-connect-an-agent-design.md
git commit -m "docs(pigrocrm): how to connect an agent over HTTP, and the decision behind it

Refs ORB-170"
```

---

### Task 12: verification, end to end, and the pull request

**Files:** none new. This task proves the whole and hands it over.

- [ ] **Step 1: The project's own gates**

```bash
uv run ruff check projects/pigrocrm && uv run ruff format --check projects/pigrocrm
uv run --no-sync pytest -q -n auto --dist loadfile -m "not slow and not planner" projects/pigrocrm -p no:cacheprovider
pnpm --filter web lint && pnpm --filter web test && pnpm --filter web build
cd projects/pigrocrm && POSTGRES_PASSWORD=build-only PIGROCRM_JWT_SECRET=build-only-and-long-enough-for-the-validator docker compose build && cd ../..
```
Expected: all green. Report any failure verbatim; do not proceed on red.

- [ ] **Step 2: Claude Code end to end against the local stack**

Bring the stack up as in Task 6 step 5 (project `orb170`, port 18080). Create the first administrator per the README's step 5 and log in at `http://127.0.0.1:18080/app/login` (note `PIGROCRM_COOKIE_SECURE` is true in the container: if the login cookie is dropped over plain HTTP, mint the token through the API with `curl` after a login on `https`, or run the SPA through the e2e recipe; the README documents this trap). Open the sidebar entry, mint a token, copy the command, then:

```bash
claude mcp add --transport http pigrocrm-local http://127.0.0.1:18080/mcp --header "Authorization: Bearer pgc_..."
claude mcp list            # pigrocrm-local: connected
claude mcp remove pigrocrm-local
docker compose -p orb170 down -v
```

Expected: `connected`. If Claude Code refuses the JSON-response mode, switch `json_response` to `False` in `http.py` and rerun Tasks 4–5's tests; the spec's §2.1 then needs one line saying so.

- [ ] **Step 3: Rebase, push, open the PR**

```bash
git fetch origin main && git rebase origin/main    # DECISIONS.md conflicts on every PR: keep both rows, ours last
git push -u origin ivansala/orb-170-pigrocrm-the-mcp-server-speaks-http-and-the-sidebar-has-a
gh pr create --title "feat(pigrocrm): the MCP server speaks HTTP and the sidebar has «Collega un agente»" --body-file - <<'EOF'
Ivan asked for a button in the sidebar that connects an agent to the CRM's MCP server. The server spoke stdio only, launched over SSH inside the api container, so nothing a button could point at existed.

What this adds

- A second transport, Streamable HTTP, stateless with JSON responses, served by a new `mcp` compose service (same image, environment and documents volume as `api`, no host port) behind the web container's nginx at `/<slug>/mcp` and `/mcp`.
- Authentication with the existing personal access tokens as bearers, resolved on the space's database with the space's settings applied. Missing or wrong tokens are one uniform 401.
- One `MCPServer` per space, built on first request and rebuilt when the space's settings rows change.
- `split_tenant_prefix`, the engine-per-space registry and the per-space base settings move to `pigrocrm.core.tenants` and both adapters use them. `mcp` is a reserved slug.
- «Collega un agente» above the profile in the sidebar, for every role. The dialog shows the endpoint, mints a token and hands over the `claude mcp add` command and the `mcpServers` JSON.

Design: `projects/pigrocrm/docs/superpowers/specs/2026-09-12-mcp-over-http-and-connect-an-agent-design.md`.

Verified

- Python and web suites green, compose build green.
- Local stack: `POST /mcp` without a token answers 401 with `WWW-Authenticate: Bearer`; `claude mcp add --transport http ... --header` connects and lists the tools.

Out of scope: OAuth, so the connectors of claude.ai and Claude Desktop are not supported yet.

Refs ORB-170
EOF
gh pr view --json mergeable,url
```

If `mergeable` is `CONFLICTING`, resolve on the branch before waiting on CI (the checks do not run on a conflicting PR).

- [ ] **Step 4: Linear**

Comment on ORB-170 with the PR link and the two verification results (the 401 curl and `claude mcp list`), move it to `In Review`. Do not move it to `Done`: that happens after the merge and the preview check, and the production deploy is Ivan's call on a `pigrocrm-v*` tag.

- [ ] **Step 5: After merge (whoever does it): preview**

```
curl -i https://preview.pigro.joinorbiters.com/mcp -X POST -d '{}'     # 401, WWW-Authenticate: Bearer
```
Then `claude mcp add` against the preview with a token minted there, `describe_schema` and one `create_customer` whose timeline entry reads «Agente AI». Only then `Done`, with the evidence in the card.
