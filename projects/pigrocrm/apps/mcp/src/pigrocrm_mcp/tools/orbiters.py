"""Who asked to join Orbiters. One read, on the one database that is not the CRM's.

`context.session` is the CRM's session and is deliberately not used here: the signup
list lives in the `orbiters` database (spec 2026-09-07 §2), reached through the same
`ensure_orbiters_database` the API uses, so both adapters agree on where the list is
and neither can accidentally read a CRM table for it. The engine is built on the first
call and kept for the life of the process, which is the same shape as the API's
`get_orbiters_session`; a process that never calls this tool never connects.

Admin only, enforced by `SignupService.list_recent` itself: these are other people's
addresses. `subscribe` -- the other public method of that service -- is *not* a tool,
and `test_mcp_surface_coverage.py` records why.
"""

import threading
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from sqlalchemy import Engine

from pigrocrm.core.config import Settings
from pigrocrm.core.db import session_factory
from pigrocrm.core.orbiters import SignupService, ensure_orbiters_database
from pigrocrm.core.orbiters.service import LIST_LIMIT_DEFAULT
from pigrocrm_mcp.context import McpContext


def register(
    mcp: MCPServer, context: McpContext, guard: Callable[..., Any], settings: Settings
) -> None:
    engine: Engine | None = None
    lock = threading.Lock()

    def _engine() -> Engine:
        nonlocal engine
        if engine is None:
            with lock:
                if engine is None:
                    engine = ensure_orbiters_database(settings)
        return engine

    @mcp.tool()
    @guard
    def list_orbiters_signups(limit: int = LIST_LIMIT_DEFAULT) -> dict[str, Any]:
        """Chi ha lasciato nome, cognome ed email su joinorbiters.com per entrare nella
        community Orbiters, dal più recente, con il profilo LinkedIn quando l'ha dato.
        Solo lettura, solo per un admin: sono dati di altre persone, e l'unica cosa da
        farne è decidere quando scrivere. `nome` e `cognome` sono vuoti solo per le
        iscrizioni raccolte quando il form chiedeva la sola email. `totale` conta tutta
        la lista anche quando `limit` ne restituisce una parte.
        """
        session = session_factory(_engine())()
        try:
            return (
                SignupService(session)
                .list_recent(context.actor, limit=limit)
                .model_dump(mode="json")
            )
        finally:
            session.close()
