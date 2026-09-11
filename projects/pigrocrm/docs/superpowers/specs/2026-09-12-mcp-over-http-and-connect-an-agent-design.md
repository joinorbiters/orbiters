# The MCP server speaks HTTP, and the sidebar has a «Collega un agente» button

Date: 2026-09-12. Tracker: ORB-170. In English, per the repository rule; the product
strings quoted below stay in Italian because they are what the product says.

## 0. Why

Ivan asked, on 2026-09-12: «nel menu laterale in basso, sopra al rimando dell'utente è
possibile aggiungere un pulsante per far collegare verso il server mcp del server?»

The button is trivial. What it can point at is not. `apps/mcp` speaks stdio only:
`__main__.py` reads `PIGROCRM_TOKEN` from the environment, resolves it once, and calls
`run("stdio")`. `docker-compose.yml` says in its first comment that there is no `mcp`
service on purpose, and that an operator runs the server on demand with
`docker compose run ... python -m pigrocrm_mcp`, typically as the `command` of an MCP
client over SSH. That is how Ivan connects today. A user of a space, who has no SSH to
the host, cannot connect an agent at all, which contradicts the second principle of the
project (`AGENTS.md`: «MCP first»).

So the button needs an endpoint, and the endpoint needs a transport and a credential a
browser can hand over. This document decides both and the button that shows them.

## 1. The decisions, in one paragraph each

**Transport.** The same server, built by the same `build_server`, is also served over
Streamable HTTP by a new `mcp` compose service, reachable at `/<slug>/mcp` for a space
and `/mcp` for the root installation. Stdio stays exactly as it is.

**Credential.** The personal access tokens that already exist, presented as
`Authorization: Bearer pgc_...`, verified by `PatService.resolve` on the space's
database with the space's settings applied. No OAuth in this version.

**Clients.** Claude Code, Cursor, Codex and any client that can send a header. The
connectors of claude.ai and Claude Desktop require OAuth 2.1 with dynamic client
registration and are out of scope; the wrapper described in §3 is the seam where an
OAuth verifier would go later, without touching a single tool.

**One server per space.** The tools `build_server` registers depend on the space's
settings (`mcp_full_access`, whether Google is configured), so an HTTP process serving
several spaces holds one `MCPServer` per slug, built on first request and cached.

**The button.** A «Collega un agente» entry above the profile block in the sidebar,
visible to every role like «Token», opening a dialog that shows the endpoint, mints a
token on the spot and hands over two snippets with the token filled in.

## 2. The service

A new module `apps/mcp/src/pigrocrm_mcp/http.py` exposes `create_app(settings=None)`
returning an ASGI application, and a module-level `app = create_app()` for uvicorn.
`docker-compose.yml` gains a service:

```yaml
mcp:
  build: { context: ../.., dockerfile: projects/pigrocrm/Dockerfile.api }
  command: uv run --no-sync uvicorn pigrocrm_mcp.http:app --host 0.0.0.0 --port 8001
  environment: *api-environment   # the api service's block, lifted into a YAML anchor
  volumes: the same documents volume as api
  depends_on: [db, api]
```

Same image as the API (`Dockerfile.api` already installs `pigrocrm-mcp`), same
environment block (the MCP tools read the same settings: database, storage, Google,
timezone), same documents volume (a tool that renders a PDF writes where the API reads).
`depends_on: api` because the API container runs `alembic upgrade head` at start-up and
the MCP process must not touch a database still being migrated; the MCP process itself
never migrates. No host port: the only door is the nginx of the `web` container.

The compose file's opening comment, which explains why there is no `mcp` service, is
rewritten to explain why there is one and how stdio still works.

### 2.1 Transport settings

`streamable_http_app(streamable_http_path="/mcp", stateless_http=True,
json_response=True, transport_security=TransportSecuritySettings(
enable_dns_rebinding_protection=False))`.

- **Stateless**: every HTTP request is a complete MCP exchange; there is no session id
  to keep alive through nginx, no server-side state to lose on a restart or a deploy,
  and no affinity to arrange. The cost is that the server cannot push notifications
  between requests (`tools/list_changed` after `refresh_schema` is one); Claude Code
  re-lists tools on its own, and the stdio transport keeps that behaviour where it
  matters.
- **JSON responses**: one request, one JSON body, no long-lived SSE stream to buffer
  or time out at the proxy. Streamable HTTP clients, Claude Code included, accept both.
- **DNS rebinding protection off**: the SDK's check compares the `Host` header against
  an allow-list, which behind a reverse proxy is the public domain and differs between
  root, preview and every self-hosted installation. The service is not published on a
  host port, so the only `Host` it ever sees is the one nginx forwards, and nginx is
  what binds the name. Turning the check off is the honest configuration, and the
  comment beside it says so.

## 3. Authentication and the actor

An ASGI wrapper around the Starlette app the SDK builds, in `http.py`, does the work the
API's `TenantPrefixMiddleware` and `get_actor` do together:

1. **Prefix.** `split_tenant_prefix(path, root_slug, segments=("mcp",))` recognises
   `/<slug>/mcp` and strips it to `/mcp`, with the same rules as the API: a reserved
   word is not a slug, the root's own slug (`PIGROCRM_ROOT_SLUG`) is the root. The
   function moves from `apps/api/src/pigrocrm_api/tenancy.py` to
   `pigrocrm.core.tenants.prefix`, gains the `segments` parameter (the API passes
   `("api", "health")`), and the API imports it from there. No behaviour change on
   the API side; its existing tests are the guard.
2. **Credential.** `Authorization: Bearer pgc_...` is required. Anything else, a
   missing header included, answers `401` with body `{"detail": "Token non valido"}`
   and `WWW-Authenticate: Bearer`, the wording `get_actor` uses. Unknown, revoked and
   deactivated-owner tokens are indistinguishable, as `PatService.resolve` already
   guarantees. The token is resolved in a short session of its own on the space's
   database, exactly as `__main__.py` does at start-up, with the space's settings
   applied (§4.2) so `Actor.full_access` is the space's answer, not the environment's.
   `PatService.resolve` stamps `last_used_at`, so the «Ultimo uso» column on the Token
   page keeps working over HTTP.
3. **Actor to the tools.** The wrapper stores the `Actor` on `scope["state"]` and calls
   the slug's Starlette app. A `ServerMiddleware` registered on that slug's `MCPServer`
   (the SDK's context-tier hook, which receives the Starlette `Request` as
   `ctx.request`) copies `request.state.actor` into a `ContextVar` for the duration of
   `call_next(ctx)`. The `actor_provider` passed to `build_server` reads that
   `ContextVar`, the way `ScopedSessionProvider.__call__` reads its session, and
   refuses outside a request for the same reason. No tool changes: `context.actor` is
   still a property that answers the right actor.

A `GET /health` on the service, without credential, answers `{"status": "ok"}` for the
compose file and for anyone debugging the container. It is not routed by nginx; from
outside, a `401` on `/<slug>/mcp` is the proof that routing and the process are alive.

## 4. Spaces

### 4.1 Routing

`deploy/nginx/spa.conf`, inside the `web` image, gains one block beside the one that
forwards `/<slug>/(api|health)` to the API:

```nginx
location ~ "^/[a-z0-9][a-z0-9-]{1,30}[a-z0-9]/mcp(/|$)" {
    set $mcp_upstream http://mcp:8001;
    proxy_pass $mcp_upstream$request_uri;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
location = /mcp {
    set $mcp_upstream http://mcp:8001;
    proxy_pass $mcp_upstream$request_uri;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

The host vhosts (`pigro.joinorbiters.conf`, `preview.pigro.joinorbiters.conf`) do not
change: their `location /` already forwards everything to the `web` container. `mcp`
joins `RESERVED_SLUGS` in `pigrocrm.core.tenants.schemas` and in
`apps/web/src/lib/tenant.ts`, with a test on each side, so no space can be called
`mcp` and shadow the root endpoint.

### 4.2 One engine and one server per space

The registry that maps a slug to a `sessionmaker` lives today in
`apps/api/src/pigrocrm_api/deps.py` (`_tenant_session_factory`, `_registry_factory`,
`_tenants_lock`, the ten-second cache of `space_settings` overrides). It is built from
`core` pieces only, so it moves to `pigrocrm.core.tenants.registry` as a class:

```python
class SpaceRegistry:
    def __init__(self, settings: Settings) -> None: ...
    def session_factory(self, slug: str | None) -> sessionmaker[Session]  # None = root
    def overrides(self, slug: str | None, session: Session) -> dict[str, str]  # 10 s TTL
    def invalidate(self, slug: str | None) -> None
    def dispose(self) -> None
```

`deps.py` keeps its function names and delegates to one module-level `SpaceRegistry`;
`invalidate_space_settings` still also drops the API's per-space storage, which stays
in the API. The move changes no behaviour and the API's tenant tests are the guard.

`http.py` holds `dict[str, _SpaceApp]` under a lock, keyed by slug (`""` for the root).
A `_SpaceApp` is the Starlette app of a `build_server(ScopedSessionProvider(factory),
actor_provider, settings=space_settings)` plus the overrides snapshot it was built
from. On each request the wrapper reads the overrides (cached ten seconds, like the
API); if they differ from the snapshot, the entry is rebuilt, so flipping «Accesso
completo per i token dell'agente» in Impostazioni → Spazio changes the tool list within
ten seconds without a restart. An unknown slug is `404` `{"detail": "spazio non
trovato"}`, the API's wording.

## 5. The button and the dialog

### 5.1 The sidebar

In `AppShell.tsx`, between the `<nav>` and the profile block, a button «Collega un
agente» with the `Plug` icon from lucide, styled like a quiet top-level entry. It is
for every role, for the same reason «Token» is a top-level entry rather than a settings
sub-item: a token belongs to whoever creates it. In the rail it is the icon alone with
`aria-label="Collega un agente"`. It opens the dialog; it navigates nowhere.

### 5.2 The dialog

`apps/web/src/features/tokens/ConnectAgentDialog.tsx`. Title «Collega un agente».
Body, top to bottom:

- **Endpoint.** `${window.location.origin}${tenantPrefix}/mcp`, read-only, with a copy
  button. `tenantPrefix` is the existing helper in `lib/tenant.ts`, so the root shows
  `/mcp` and a space shows `/<slug>/mcp`.
- **Token.** One line of explanation, «Serve un token di accesso: viene mostrato una
  volta sola.», a name field prefilled with «Claude Code», and a «Crea il token» button
  that calls the existing `useCreateToken`. Errors render as on the Token page
  (`fieldErrorFrom`, `toProblem`). After creation the field and button give way to the
  token in monospace with its own copy button, and the same warning the Token page
  shows: the token inherits the whole role, treat it like a password.
- **Snippets.** Two read-only blocks with copy buttons. Before a token exists they
  carry the placeholder `<token>`; after, the real value. The server name is
  `pigrocrm` for the root and `pigrocrm-<slug>` for a space, so two spaces in one
  client do not collide.

  ```
  claude mcp add --transport http pigrocrm-<slug> https://<host>/<slug>/mcp --header "Authorization: Bearer <token>"
  ```

  ```json
  {"mcpServers": {"pigrocrm-<slug>": {"type": "http", "url": "https://<host>/<slug>/mcp",
    "headers": {"Authorization": "Bearer <token>"}}}}
  ```

- **Footer.** A link «Gestisci i token» to `/app/token` and a «Chiudi» button.

Leaving while a freshly minted token is on screen asks the same question the Token
page asks (`LEAVE_WARNING`, `useBlocker`, `enableBeforeUnload`). That guard is
extracted from `TokensPanel.tsx` into a hook `useUnsavedTokenGuard(issued)` in the same
feature, used by both, so the two surfaces cannot drift. Closing the dialog with a
token on screen goes through `window.confirm` with the same text.

## 6. Documentation

- `projects/pigrocrm/README.md`: a section «Connect an agent» with the two snippets,
  the note that the token is a Bearer, and the sentence that claude.ai and Desktop
  connectors need OAuth and are not supported yet.
- `docker-compose.yml`: the head comment rewritten (§2).
- `projects/pigrocrm/AGENTS.md`: the layout line for `apps/mcp/` reads «the MCP server,
  stdio and Streamable HTTP. Imports core.»
- `.env.example`: no new variable. The «MCP surface» comment gains one sentence saying
  the same switch governs the HTTP transport.
- `docs/design/DECISIONS.md`: one row, dated 2026-09-12, recording that the HTTP
  transport authenticates with the existing PATs as bearers and that OAuth is deferred
  until a client that needs it is in scope.

## 7. Deploy

Nothing new to configure. Merging to `main` deploys the preview; the production site
moves on a `pigrocrm-v*` tag when Ivan asks (`docs/tracker.md`, the release rule). The
deploy's health check stays on the API. After the preview deploy the verification is:

```
curl -i https://preview.pigro.joinorbiters.com/<slug>/mcp        # 401, WWW-Authenticate: Bearer
claude mcp add --transport http pigrocrm-<slug> <url> --header "Authorization: Bearer <token>"
claude mcp list                                                 # connected
```

followed by one read tool (`describe_schema`) and one write tool (`create_customer`)
whose timeline entry must show «Agente AI».

## 8. Verification

- `apps/mcp/tests/test_http_transport.py`, on the Postgres testcontainer the MCP tests
  already use, driving `create_app(...)` in-process through `httpx.ASGITransport` and
  the SDK's own `streamable_http_client(url, http_client=...)`:
  - no header, a non-`pgc_` bearer, an unknown token and a revoked token all answer
    `401` with the same body;
  - a valid token: `initialize`, `tools/list`, `describe_schema`;
  - `create_customer` over HTTP leaves a timeline entry whose actor is the token's user
    (the «Agente AI» label the timeline already renders for PAT actors);
  - with `mcp_full_access` false the privileged tools are absent from `tools/list`;
    with it true, present; flipping the space setting rebuilds the server;
  - `/<unknown>/mcp` is `404`; `/mcp/app` style paths are not swallowed;
  - two provisioned spaces: a customer created in one is not listed in the other.
- `packages/core/tests/test_tenants.py`: `mcp` is reserved; `split_tenant_prefix` with
  `segments=("mcp",)` and the root-slug rule.
- `apps/api/tests`: unchanged and green after the moves of §3 (step 1) and §4.2.
- `apps/web`: `AppShell.test.tsx` gains «the entry renders for admin and collaboratore
  and opens the dialog»; `ConnectAgentDialog.test.tsx` covers the URL from the prefix,
  the placeholder before creation, the token inside both snippets after, the copy
  buttons and the leave guard; `tenant.test.ts` covers the reserved word.
- `.github/preflight.json` needs no new check: the pytest globs cover `apps/mcp`, the
  web checks cover the dialog, and `docker compose build` builds the new service.

## 9. Out of scope, and the two risks to retire first

Out of scope: OAuth and the claude.ai and Desktop connectors; server-to-client
notifications over HTTP; rate limiting on the endpoint (the token is 32 random bytes
and the `401` is uniform); Gmail and Drive for spaces, which the spaces design already
excludes.

Two things the implementation plan verifies before anything else, because the design
leans on them and they were read in the installed SDK (`mcp==2.0.0`) rather than
exercised:

1. That a `ServerMiddleware` receives the Starlette `Request` as `ctx.request` under
   the stateless Streamable HTTP transport, and that a `ContextVar` set inside it is
   visible to the tool function `call_next` reaches. If it is not, the fallback is to
   read the actor from `ctx.request.state` inside `_guard`, which every tool already
   passes through.
2. That Claude Code connects to a stateless, JSON-response Streamable HTTP endpoint
   with a custom header, end to end, against a local `docker compose up`.
