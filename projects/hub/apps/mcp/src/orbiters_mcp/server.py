"""`build_server`: the tools, over a session factory a test can replace.

An admin's own tool by construction. The process is started by an MCP client on a
machine that already holds the hub's database URL, and everything it can do is what
the hub's admin API will do behind its login (hub spec, step 3). There is no actor and
no permission check here because there is exactly one kind of caller; when a personal
token arrives for the hub, this is where it is resolved.

One session per tool call, closed whatever happened: the SDK dispatches sync tools on
a thread pool, and a session shared across calls is the defect PigroCRM's MCP server
measured as zero rows written under concurrency.
"""

from typing import Any

from mcp.server import MCPServer
from sqlalchemy.orm import Session, sessionmaker

from orbiters_core.service import LIST_LIMIT_DEFAULT, SignupService

SessionFactory = sessionmaker[Session]

INSTRUCTIONS = (
    "Orbiters, la community di freelance di joinorbiters.com. Gli strumenti leggono la "
    "lista di chi ha chiesto di entrare: sono dati di altre persone, da usare solo per "
    "decidere quando e cosa scrivere loro."
)


def build_server(factory: SessionFactory) -> MCPServer:
    mcp = MCPServer("Orbiters", instructions=INSTRUCTIONS)

    @mcp.tool()
    def list_signups(limit: int = LIST_LIMIT_DEFAULT) -> dict[str, Any]:
        """Chi ha lasciato nome, cognome ed email su joinorbiters.com per entrare nella
        community Orbiters, dal più recente, con il profilo LinkedIn quando l'ha dato.
        Solo lettura. `nome` e `cognome` sono vuoti solo per le iscrizioni raccolte
        quando il form chiedeva la sola email. `totale` conta tutta la lista anche
        quando `limit` ne restituisce una parte."""
        session = factory()
        try:
            return SignupService(session).list_recent(limit=limit).model_dump(mode="json")
        finally:
            session.close()

    return mcp
