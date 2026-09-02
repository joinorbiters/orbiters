import threading
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from pigrocrm.core.actor import Actor, Role
from pigrocrm.core.auth.pat_service import PAT_PREFIX, PatService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.tokens import decode_token
from pigrocrm.core.config import Settings, get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.errors import DomainError
from pigrocrm.core.storage import DocumentStorage, storage_from_settings

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


def _get_session_factory() -> sessionmaker[Session]:
    global _engine, _factory
    if _factory is None:
        with _engine_lock:
            if _factory is None:  # a concurrent caller may have just finished building it
                _engine = create_engine_from_settings(get_settings())
                _factory = session_factory(_engine)
    return _factory


def get_session() -> Iterator[Session]:
    session = _get_session_factory()()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_snapshot_session() -> Iterator[Session]:
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
    session = _get_session_factory()()
    try:
        yield session
    finally:
        session.close()


SnapshotSessionDep = Annotated[Session, Depends(get_snapshot_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_storage(settings: SettingsDep) -> DocumentStorage:
    """One backend per process, chosen from settings. `settings` is already
    `get_settings`'s own `lru_cache`d singleton, so this builds at most one
    `GDriveStorage` (whose own token cache is then shared across requests) rather
    than re-authenticating on every call."""
    return storage_from_settings(settings)


StorageDep = Annotated[DocumentStorage, Depends(get_storage)]


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
            return PatService(session).resolve(header[7:])
        except DomainError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token non valido") from exc

    token = request.cookies.get(ACCESS_COOKIE)
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
