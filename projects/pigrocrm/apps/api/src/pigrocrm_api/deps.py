import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from pigrocrm.core.actor import Actor, Role
from pigrocrm.core.auth.pat_service import PAT_PREFIX, PatService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.tokens import decode_token
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.errors import DomainError
from pigrocrm.core.orbiters import ensure_orbiters_database
from pigrocrm.core.space_settings import SpaceSettingsService, apply_overrides
from pigrocrm.core.storage import DocumentStorage, LocalFileStorage, storage_from_settings
from pigrocrm.core.tenants import TenantService, ensure_tenants_database
from pigrocrm.core.tenants.database import tenant_database_url
from pigrocrm_api.tenancy import first_cookie, tenant_slug

ACCESS_COOKIE = "pigrocrm_access"
REFRESH_COOKIE = "pigrocrm_refresh"

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None
# Guards the two lines below: FastAPI runs sync dependencies in a thread pool, so
# several requests can reach a cold start at once. Without this, each could pass the
# "is it built yet" check before any of them finishes, each build its own Engine, and
# leave the module globals pointing at whichever one wrote last -- wasteful, and not a
# guarantee this codebase wants to lean on.
_engine_lock = threading.Lock()

_storage: DocumentStorage | None = None
# The same guarantee as `_engine_lock`, for the same reason and with the same shape:
# one storage per process even when several requests reach a cold start at once. It
# matters more here than for the engine, because the object being cached holds a token
# cache -- two instances mean two `GoogleTokenClient`s and an extra OAuth round-trip
# per request that lost the race.
_storage_lock = threading.Lock()


def _get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    """The root's engine, built once from the first caller's settings. Callers with a
    request pass the settings dependency through, so a test's override of
    `get_settings` decides the server; callers without one (`_fresh_session`) get the
    process settings, which in production are the same object."""
    global _engine, _factory
    if _factory is None:
        with _engine_lock:
            if _factory is None:  # a concurrent caller may have just finished building it
                _engine = create_engine_from_settings(settings or get_settings())
                _factory = session_factory(_engine)
    return _factory


def reset_session_factories() -> None:
    """Forgets the root's engine along with every space's (`reset_tenant_caches`), for a
    test that points the whole process at another server through `get_settings`."""
    global _engine, _factory
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _factory = None
    _overrides_cache.clear()
    reset_tenant_caches()


# --- Spaces (spec 2026-09-08). One engine per space per process, built on first use and
# kept, exactly like the root's above; the registry that says which database a slug
# owns is a sidecar of its own, opened the same way.
_tenant_factories: dict[str, sessionmaker[Session]] = {}
_tenants_registry: sessionmaker[Session] | None = None
# Re-entrant, and it has to be: building a space's engine (`_tenant_session_factory`)
# holds this lock while it asks the registry, and the registry's own first build
# (`_registry_factory`) takes the same lock. A plain Lock deadlocks the first request a
# space ever receives -- found the hard way, with a test suite that never finished.
_tenants_lock = threading.RLock()


def _registry_factory(settings: Settings) -> sessionmaker[Session]:
    global _tenants_registry
    if _tenants_registry is None:
        with _tenants_lock:
            if _tenants_registry is None:
                _tenants_registry = session_factory(ensure_tenants_database(settings))
    return _tenants_registry


def get_tenants_registry_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[Session]:
    """A session on the registry database -- the list of spaces, never a space.

    `settings` arrives as a dependency rather than a `get_settings()` call so a test's
    override of `get_settings` decides which server the registry lives on."""
    session = _registry_factory(settings)()
    try:
        yield session
    finally:
        session.close()


TenantsRegistryDep = Annotated[Session, Depends(get_tenants_registry_session)]


def _tenant_session_factory(slug: str, settings: Settings) -> sessionmaker[Session]:
    factory = _tenant_factories.get(slug)
    if factory is None:
        with _tenants_lock:
            factory = _tenant_factories.get(slug)
            if factory is None:
                registry = _registry_factory(settings)()
                try:
                    # `NotFound` -> 404 «spazio non trovato» through the domain handler:
                    # a slug nobody registered is a wrong address, not a server fault.
                    tenant = TenantService(registry, settings).get(slug)
                finally:
                    registry.close()
                engine = create_engine(
                    tenant_database_url(settings, tenant.db_name), pool_pre_ping=True, future=True
                )
                factory = session_factory(engine)
                _tenant_factories[slug] = factory
    return factory


def _factory_for(request: Request, settings: Settings) -> sessionmaker[Session]:
    slug = tenant_slug(request)
    return _tenant_session_factory(slug, settings) if slug else _get_session_factory(settings)


def reset_tenant_caches() -> None:
    """Forgets every space's engine and the registry, for tests that provision spaces
    against a container and must not leak engines across settings."""
    global _tenants_registry
    with _tenants_lock:
        for factory in _tenant_factories.values():
            bind = factory.kw.get("bind")
            if isinstance(bind, Engine):
                bind.dispose()
        _tenant_factories.clear()
        _tenants_registry = None


def get_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Iterator[Session]:
    session = _factory_for(request, settings)()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_snapshot_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Iterator[Session]:
    """A second session per request, untouched by anything else in the request.

    Only the dashboards use it, and they need it. A dashboard is one transaction in
    `REPEATABLE READ` so that every figure on the page was true at one instant (spec
    §7.1), Postgres refuses to change the isolation level once a transaction has begun,
    and `DashboardService._open_snapshot` raises rather than silently degrading to
    `READ COMMITTED` -- where a card and its own drill-through can disagree and nothing
    about re-reading the code would say so.

    `get_actor` resolves the cookie by reading `users` **on `SessionDep`**, and that read
    autobegins a transaction. So a dashboard route taking `SessionDep` would raise on
    every single request: not a race, not a load-dependent bug, every request. Two
    sessions is the fix, and it is the same one the MCP adapter has used since Task 4A-1 --
    `__main__.py` resolves the PAT in its own short-lived session so the tool's session is
    untouched when the tool body runs.

    A distinct callable, therefore a distinct key in FastAPI's per-request dependency
    cache: a route asking for both gets two sessions, deliberately. The cost is one extra
    pooled connection for the life of the request, paid only by the routes that ask.
    """
    session = _factory_for(request, settings)()
    try:
        yield session
    finally:
        session.close()


SnapshotSessionDep = Annotated[Session, Depends(get_snapshot_session)]


def request_base_settings(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Settings:
    """The environment's settings as *this request* may see them, before the database
    has its say.

    A space does not inherit the root's Google: the client, its secret and the token key
    are blanked, so a space either configures its own (Impostazioni → Spazio) or has no
    Gmail and no Drive -- `gmail_configured` false, sections hidden, endpoints 409. Its
    public URL is the root's plus the slug, which is where Google will redirect to, and
    documents default to disk under the space's own folder. The root sees the
    environment untouched. Chained on `get_settings` so a test's override of that one
    dependency still reaches every route.
    """
    slug = tenant_slug(request)
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


BaseSettingsDep = Annotated[Settings, Depends(request_base_settings)]

# The rows of `space_settings`, per database, remembered briefly: every request asks
# for its settings, and a read of a one-row table on each of them is cheap but not
# free. Ten seconds, and `invalidate_space_settings` after every write, so the page
# that just saved sees what it saved.
_overrides_cache: dict[str, tuple[float, dict[str, str]]] = {}
OVERRIDES_TTL_SECONDS = 10.0


def _space_overrides(request: Request, base: Settings, session: Session) -> dict[str, str]:
    key = tenant_slug(request) or ""
    cached = _overrides_cache.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < OVERRIDES_TTL_SECONDS:
        return cached[1]
    overrides = SpaceSettingsService(session, base).overrides()
    _overrides_cache[key] = (now, overrides)
    return overrides


def invalidate_space_settings(slug: str | None) -> None:
    """After a write to `space_settings`: forget the cached rows and the storage built
    from them, for this database only."""
    _overrides_cache.pop(slug or "", None)
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
    return apply_overrides(base, _space_overrides(request, base, session))


SettingsDep = Annotated[Settings, Depends(get_request_settings)]

_orbiters_factory: sessionmaker[Session] | None = None
_orbiters_lock = threading.Lock()


def get_orbiters_session() -> Iterator[Session]:
    """A session on the `orbiters` database, which is not the CRM's.

    Built lazily, once per process, behind its own lock -- the same shape as
    `_get_session_factory`. Lazily is load-bearing here: `ensure_orbiters_database`
    runs `CREATE DATABASE` and `create_all` the first time anyone asks, so an
    installation that never serves the Orbiters page never creates the database, and
    the API boots even where that user may not create databases at all. The first
    signup, not the deploy, is what pays for it and what fails if it cannot be done.
    """
    global _orbiters_factory
    if _orbiters_factory is None:
        with _orbiters_lock:
            if _orbiters_factory is None:
                _orbiters_factory = session_factory(ensure_orbiters_database(get_settings()))
    session = _orbiters_factory()
    try:
        yield session
    finally:
        session.close()


OrbitersSessionDep = Annotated[Session, Depends(get_orbiters_session)]


def _fresh_session() -> Session:
    """A session the caller owns and closes -- deliberately *not* the request's.

    This is what `get_storage` hands to `storage_from_settings`, and it is a callable
    rather than a `Session` for two reasons. The storage it belongs to outlives every
    request (one per process), so it cannot hold a session that must not; and it opens
    one only when it actually resolves an account, which is why a process with
    `PIGROCRM_STORAGE_BACKEND=gdrive` and nobody's Drive connected yet still starts.

    The request's own `SessionDep` would be wrong even where the lifetimes happened to
    line up: `LazyUserDriveStorage` closes what it opens, and it records a revoked grant
    by committing on its own behalf -- both of which would reach into the transaction
    the route is in the middle of.
    """
    return _get_session_factory()()


_tenant_storages: dict[str, DocumentStorage] = {}


def get_storage(request: Request, settings: SettingsDep) -> DocumentStorage:
    """One backend per process, chosen from settings and built once behind a lock.

    Once, and cached: the two Drive backends hold a token cache that only earns its keep
    across requests (`GoogleTokenClient` is documented as one per process), so building
    per request would turn every document read into an OAuth round-trip. `settings` is
    `get_settings`'s own `lru_cache`d singleton, so there is only ever one answer to
    cache -- and it therefore reads the settings of the *first* request to ask, which is
    also true of `_get_session_factory`'s engine and is what makes a settings change a
    restart rather than a surprise mid-process.

    Still a FastAPI dependency, and that is what makes it overridable: the tests replace
    it with a `LocalFileStorage` under `tmp_path` (`conftest.py`) rather than letting
    uploads write into the repository's own working tree. The cache is cleared through
    `reset_storage_cache()` below, which is what the tests that change the backend call.

    **What the lock is held across, on one configuration.** With a service account
    configured, `storage_from_settings` verifies the root folder before it returns
    (`GDriveStorage.verify_root_accessible`), which is a Drive round-trip with a retry
    budget -- so the first request to ask for a document backend holds `_storage_lock`
    across a network call, and any other request that arrives in that window waits for
    it. Kept deliberately: it happens once per process, every waiter needs that same
    answer before it can do anything with a document, and the alternative -- build
    outside the lock and swap the result in -- would pay a second verification round-trip
    and hand one of the two builds' token cache straight to the garbage collector, which
    is the exact waste this cache exists to prevent. The other two backends make no call
    here at all: `local` touches a `Path`, and the titolare's-own-Drive route reads
    nothing until its first operation (`LazyUserDriveStorage`).
    """
    slug = tenant_slug(request)
    if slug is not None:
        # A space's documents live on disk beside the root's, in their own folder,
        # unless the space configured Google and chose Drive (Impostazioni → Spazio):
        # then its own Drive account, resolved from its own database. Never the root's
        # storage: that Drive account is the root's, and `_fresh_session` opens the
        # root's database.
        storage = _tenant_storages.get(slug)
        if storage is None:
            with _storage_lock:
                storage = _tenant_storages.get(slug)
                if storage is None:
                    if settings.storage_backend == "gdrive":
                        factory = _tenant_session_factory(slug, settings)
                        storage = storage_from_settings(settings, session_factory=lambda: factory())
                    else:
                        root = Path(settings.storage_local_root) / "tenants" / slug
                        storage = LocalFileStorage(root)
                    _tenant_storages[slug] = storage
        return storage

    global _storage
    if _storage is None:
        with _storage_lock:
            if _storage is None:  # a concurrent caller may have just finished building it
                _storage = storage_from_settings(settings, session_factory=_fresh_session)
    return _storage


StorageDep = Annotated[DocumentStorage, Depends(get_storage)]


def reset_storage_cache() -> None:
    """Forgets the process's storage, so the next `get_storage` builds a new one.

    Exists for the tests, and named so that they no longer have to assign this module's
    private `_storage` to say what they mean. Two of them do say it -- the one that
    drives a whole Drive installation over HTTP, and the one that asserts the cache
    itself -- and a test that pokes a private global is a test that silently stops
    working the day the global is renamed or a second one joins it. This function is
    that knowledge, kept next to the cache it clears.

    Under `_storage_lock`, for the same reason `get_storage` builds under it: clearing
    the cache while another thread is between the check and the assignment would let
    that thread's build survive the reset. Nothing is rebuilt here -- the backend is
    resolved lazily by the next caller, which is also what makes this safe to call
    before a test has settled which settings the process should read.
    """
    global _storage
    with _storage_lock:
        _storage = None


def get_actor(request: Request, session: SessionDep, settings: SettingsDep) -> Actor:
    """Two credentials, one actor: the browser presents a JWT cookie, an agent presents
    a PAT. Everything downstream is identical.

    Precedence, in order -- deterministic, not a race between the two credentials:

    1. `Authorization: Bearer pgc_...` -- a header that looks like a PAT always wins
       over any cookie, even a valid one. If `PatService.resolve` fails (unknown,
       revoked, or the owning user deactivated), this raises 401 immediately; the
       cookie is never consulted, even when one is present and would otherwise work.
    2. Any other `Authorization` header -- absent, not `Bearer `, or a `Bearer` value
       that does not start with `pgc_` -- is ignored outright, and resolution falls
       back to the `ACCESS_COOKIE` cookie.
    """
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer ") and header[7:].startswith(PAT_PREFIX):
        try:
            # `settings`, so a space's own `mcp_full_access` (Impostazioni → Spazio) is
            # what stamps `Actor.full_access`, not the process environment's.
            return PatService(session, settings=settings).resolve(header[7:])
        except DomainError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token non valido") from exc

    token = first_cookie(request, ACCESS_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticazione richiesta")
    try:
        payload = decode_token(token, settings, expected_type="access")
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessione scaduta") from exc

    try:
        user = UserRepository(session).get_active(payload.sub)
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo") from exc

    role: Role = user.ruolo  # type: ignore[assignment]
    return Actor(id=user.id, type="user", role=role)


ActorDep = Annotated[Actor, Depends(get_actor)]
# Same dependency, named for what it does at the call site: a router that depends on
# it is declaring "this endpoint requires an authenticated actor."
require_actor = get_actor
