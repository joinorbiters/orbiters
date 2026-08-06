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
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_actor(request: Request, session: SessionDep, settings: SettingsDep) -> Actor:
    """Two credentials, one actor: the browser presents a JWT cookie, an agent presents
    a PAT. Everything downstream is identical."""
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

    user = UserRepository(session).get(payload.sub)
    if user is None or not user.attivo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo")

    role: Role = user.ruolo  # type: ignore[assignment]
    return Actor(id=user.id, type="user", role=role)


ActorDep = Annotated[Actor, Depends(get_actor)]
# Same dependency, named for what it does at the call site: a router that depends on
# it is declaring "this endpoint requires an authenticated actor."
require_actor = get_actor
