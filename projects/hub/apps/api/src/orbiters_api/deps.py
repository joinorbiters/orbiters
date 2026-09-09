"""One engine per process, one session per request."""

import threading
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from orbiters_core.admin import AdminRead, AdminService
from orbiters_core.config import Settings, get_settings
from orbiters_core.db import create_engine_from_settings, session_factory

ADMIN_COOKIE = "orbiters_admin"

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None
_lock = threading.Lock()


def _get_session_factory() -> sessionmaker[Session]:
    global _engine, _factory
    if _factory is None:
        with _lock:
            if _factory is None:
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


def get_admin(request: Request, session: SessionDep, settings: SettingsDep) -> AdminRead:
    """The admin behind the session cookie, or 401. Every admin route depends on this and
    nothing else: there is one role in the hub's admin area."""
    admin = AdminService(session, settings).resolve(request.cookies.get(ADMIN_COOKIE))
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticazione richiesta")
    return admin


AdminDep = Annotated[AdminRead, Depends(get_admin)]
