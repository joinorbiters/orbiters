import functools
import inspect
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError

from pigrocrm.core.errors import DomainError
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm_mcp.context import ActorProvider, McpContext, SessionProvider
from pigrocrm_mcp.errors import to_agent_message, to_domain_error
from pigrocrm_mcp.resources import entities
from pigrocrm_mcp.tools.schema import ENTITY_TYPES, entity_schema

INSTRUCTIONS = """PigroCRM — CRM per freelancer e piccole startup italiane.

Prima di creare o aggiornare un'entità, chiama `describe_schema` per conoscere i campi
personalizzati definiti dall'utente: non sono codificati negli strumenti e cambiano nel tempo.
Per leggere il contesto completo usa le risorse `customer://`, `person://` e `deal://`.
Nulla viene cancellato fisicamente: le operazioni di archiviazione sono reversibili.
"""


def _as_protocol_error(exc: DomainError) -> ResourceError:
    """Carry `to_agent_message`'s diagnosis through the one exception family the
    installed SDK (mcp==2.0.0) will not silently replace with boilerplate.

    Verified against the installed package, not assumed from the plan: a resource
    template's error path (`ResourceTemplate.create_resource`, then
    `MCPServer._handle_read_resource`) rewrites any exception that is not already
    `ResourceError`/`ResourceNotFoundError`/`MCPError` into a generic "Error
    creating/reading resource ..." string, discarding whatever message it carried
    — confirmed by calling a live server in-process and inspecting the exception
    a client actually receives. A tool's error path (`Tool.run`) has no such
    rewrite; it interpolates the original message regardless of exception type,
    so `ValueError` would have worked there. Raising this exempted type from a
    single shared guard is what lets both call sites keep a diagnosis intact.
    """
    message = to_agent_message(exc)
    if exc.code == "not_found":
        return ResourceNotFoundError(message)
    return ResourceError(message)


def _guard[T: Callable[..., Any]](fn: T) -> T:
    """Every tool and resource renders a domain error as guidance instead of
    leaking a stack trace or a bare status code.

    `functools.wraps` is load-bearing, not cosmetic. `mcp.tool()`/`mcp.resource()`
    infer a JSON Schema from `inspect.signature(fn)`, and that inspection follows
    `__wrapped__` by default — confirmed directly against the installed SDK, where
    a wrapper without it produced two *required* "args"/"kwargs" fields instead of,
    say, `entity_type`, because the tool manager saw this wrapper's own bare
    `(*args, **kwargs)` signature instead of the guarded function's real one.

    `except ValueError` (which also catches `pydantic.ValidationError`, a subclass)
    is what keeps an argument-conversion failure — `uuid.UUID(bad_string)` inside a
    tool, or constructing one of `pigrocrm.core`'s own Create/Update/ListQuery
    schemas from caller-supplied data — from reaching the client as raw, English,
    link-carrying text instead of the same rendered guidance a hand-raised
    `DomainError` gets. `to_domain_error` does the translation; see its own
    docstring for why the two sources need different handling despite both
    arriving here as `ValueError`. This must stay a single guard fixing both,
    not a per-tool try/except: a fix that only covered today's tools would not
    cover the next one.
    """
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except DomainError as exc:
                raise _as_protocol_error(exc) from exc
            except ValueError as exc:
                raise _as_protocol_error(to_domain_error(exc)) from exc

        return cast(T, async_wrapper)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except DomainError as exc:
            raise _as_protocol_error(exc) from exc
        except ValueError as exc:
            raise _as_protocol_error(to_domain_error(exc)) from exc

    return cast(T, wrapper)


def build_server(session_provider: SessionProvider, actor_provider: ActorProvider) -> MCPServer:
    context = McpContext(session_provider, actor_provider)
    mcp = MCPServer("PigroCRM", instructions=INSTRUCTIONS)

    @mcp.tool()
    @_guard
    def describe_schema(entity_type: EntityType) -> dict[str, Any]:
        """Campi nativi e personalizzati attualmente definiti per un'entità.

        Legge dal database a ogni chiamata: usalo prima di creare o aggiornare.
        """
        return entity_schema(context, entity_type)

    @mcp.tool()
    @_guard
    async def refresh_schema(ctx: Context) -> dict[str, int]:
        """Ricarica i campi personalizzati e riporta quanti sono definiti per entità.

        Dopo aver chiamato questo strumento, richiama `describe_schema` per vedere
        i campi aggiornati: a seconda della versione di protocollo negoziata con
        questo client, potresti non ricevere alcun avviso automatico di
        cambiamento. Non aspettare una notifica che potrebbe non arrivare mai.
        """
        counts: dict[str, int] = {
            entity: len(entity_schema(context, entity)["custom_fields"]) for entity in ENTITY_TYPES
        }
        # Best-effort, kept because it is correct and harmless -- not because it
        # reliably reaches the client. Verified against the installed SDK
        # (mcp==2.0.0), not assumed: with the default connection mode (`Client(
        # server)`, `mode="auto"`), this negotiates the modern 2026-07-28
        # protocol, under which `notifications/tools/list_changed` is delivered
        # only to a client that opened a `subscriptions/listen` stream —
        # `mcp.server.lowlevel.server.Server.get_capabilities`'s own docstring
        # says so, and a live reproduction confirmed it: a `Client(server)`
        # connection with a registered `message_handler` received zero messages
        # after this call, even though the server advertises
        # `tools.listChanged=True` for that same connection. Forcing the classic
        # handshake protocol instead (`Client(server, mode="legacy")`, which
        # negotiates 2025-11-25) delivered a `ToolListChangedNotification`
        # immediately, despite that connection advertising `listChanged=False`.
        # See `test_refresh_schema_notification_is_a_documented_sdk_limitation`
        # for the reproduction this comment is based on. Re-verify both
        # directions the next time `mcp` is upgraded — either the modern
        # protocol's listen-stream requirement, or this SDK's capability
        # advertisement for it, may have changed.
        await ctx.session.send_tool_list_changed()
        return counts

    @mcp.resource("customer://{customer_id}")
    @_guard
    def customer_resource(customer_id: str) -> str:
        """Scheda completa di un cliente: dati fiscali, contatti, deal e timeline."""
        return entities.render_customer(context, UUID(customer_id))

    @mcp.resource("person://{person_id}")
    @_guard
    def person_resource(person_id: str) -> str:
        """Scheda completa di una persona."""
        return entities.render_person(context, UUID(person_id))

    @mcp.resource("deal://{deal_id}")
    @_guard
    def deal_resource(deal_id: str) -> str:
        """Scheda completa di un deal, incluso stato di pipeline e timeline."""
        return entities.render_deal(context, UUID(deal_id))

    from pigrocrm_mcp.tools import register_entity_tools

    register_entity_tools(mcp, context, _guard)
    return mcp
