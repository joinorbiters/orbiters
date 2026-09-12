import functools
import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any, cast
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError

from pigrocrm.core.config import Settings, get_settings, gmail_configured
from pigrocrm.core.errors import DomainError
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.storage import DocumentStorage, storage_from_settings
from pigrocrm_mcp.context import ActorProvider, McpContext, SessionProvider
from pigrocrm_mcp.errors import to_agent_message, to_domain_error
from pigrocrm_mcp.resources import entities
from pigrocrm_mcp.tools.schema import ENTITY_TYPES, entity_schema

INSTRUCTIONS = """PigroCRM — CRM per freelancer e piccole startup italiane.

Prima di creare o aggiornare un'entità, chiama `describe_schema` per conoscere i campi
personalizzati definiti dall'utente: non sono codificati negli strumenti e cambiano nel tempo.
Per leggere il contesto completo usa le risorse `customer://`, `person://` e `deal://`.
Nulla viene cancellato fisicamente: le operazioni di archiviazione sono reversibili.
L'unica eccezione e' `discard_proforma`, che non si ripristina: una proforma scartata si ricrea.
`confirm_proforma` non torna indietro, ma non chiude nulla: una proforma confermata resta
modificabile e si puo' ancora scartare.
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


def build_server(
    session_provider: SessionProvider,
    actor_provider: ActorProvider,
    storage: DocumentStorage | None = None,
    settings: Settings | None = None,
) -> MCPServer:
    # One session per logical call (Task 4A-1, residual R1). `_guard` opens the
    # scope via `session_provider.scope()` when the provider exposes one --
    # `ScopedSessionProvider`, used in production (`__main__.py`) -- and
    # `McpContext.session` then resolves to the one session bound to it, however
    # many times a tool or a resource render reads the property
    # (`resources/entities.py`'s renders read it up to four times). A plain
    # callable provider (a test passing `lambda: session`, as this package's own
    # `server` fixture still does) has no `.scope` attribute, so it falls back to a
    # null scope and keeps the old, single-shared-session behaviour that fixture
    # relies on. The measurement this replaces: 10 concurrent writes against one
    # shared Session produced 0 successes and 0 rows.
    #
    # `storage` is an explicit, optional parameter -- not always resolved
    # internally from `get_settings()` -- for the same reason `session_provider`/
    # `actor_provider` are already constructor-injected rather than imported: a
    # test builds its own isolated backend (a tmp-dir-backed `LocalFileStorage`)
    # instead of a document/version tool call writing real files into this
    # repository's own working tree under the default `./var/documents` root.
    # `__main__.py` never passes one, so production still gets exactly one
    # `storage_from_settings(...)` per process, same as the API -- `build_server` is
    # called once, at start-up, and the storage it builds is the one every tool call
    # then shares (which is what keeps a Drive backend's access token cached across
    # calls instead of re-authenticating on each).
    #
    # `settings` is optional for the same reason and resolved the same way. It decides
    # one thing only: whether the Gmail tools are registered at all. A test that wants
    # them passes a configured `Settings`; every other caller, `__main__.py` included,
    # gets the process's own -- and an installation with no Google client therefore has
    # no Gmail surface rather than a broken one (spec 5.3).
    resolved_settings = settings or get_settings()
    # `resolved_settings`, not a second `get_settings()`: an installation is something a
    # caller declares once. A test that says "storage_backend is gdrive" and lets this
    # build the storage was, until this line, silently given the *process's* backend
    # instead -- and production is unaffected either way, since `__main__.py` passes
    # neither argument.
    #
    # `session_factory` is what the titolare's-own-Drive backend needs and no other
    # backend does: the account and the folder it writes into live in a row, so the
    # storage has to be able to open a session at each operation, long after this
    # function returned. `new_session` opens a fresh one the storage owns and closes
    # (see `ScopedSessionProvider.new_session`); a plain callable provider does not have
    # it, and `storage_from_settings` then refuses that configuration by name rather
    # than closing the session a tool call is running in.
    context = McpContext(
        session_provider,
        actor_provider,
        storage
        or storage_from_settings(
            resolved_settings, session_factory=getattr(session_provider, "new_session", None)
        ),
    )
    mcp = MCPServer("PigroCRM", instructions=INSTRUCTIONS)

    # Resolved once, here, rather than per call (Task 4A-1). `ScopedSessionProvider`
    # (production, via `__main__.py`) exposes `.scope()`; a plain callable provider
    # (a test passing `lambda: session`, as this package's own `server` fixture
    # still does) does not, and falls back to `nullcontext()` -- the old behaviour,
    # one session shared for the whole lifetime of whatever holds the provider.
    _scope: Callable[[], AbstractContextManager[Any]] | None = getattr(
        session_provider, "scope", None
    )

    def _session_scope() -> AbstractContextManager[Any]:
        return _scope() if _scope is not None else nullcontext()

    def _guard[T: Callable[..., Any]](fn: T) -> T:
        """Every tool and resource renders a domain error as guidance instead of
        leaking a stack trace or a bare status code -- and, whatever else it does,
        always leaves `context.session` usable for the *next* call.

        A nested function, not a module-level one: it needs `context` in scope to
        roll back its session, and `context` only exists once `build_server` has
        constructed it. `register_entity_tools(mcp, context, _guard)` below passes
        this closure on, exactly as it passed the old module-level function.

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

        `with _session_scope():` wraps the whole call (Task 4A-1, residual R1): with
        a real `ScopedSessionProvider`, this opens one `Session` for this logical
        call and closes it on the way out whatever happened, so a raw DBAPI failure
        poisoning a transaction can no longer follow the next unrelated call the way
        a single, process-lifetime session used to let it. `context.session.
        rollback()` stays in every arm regardless, because `_session_scope()` is a
        no-op `nullcontext()` when `session_provider` is a plain callable — this
        package's own `server` fixture builds one that way, sharing one `Session`
        across every tool call in a test the way `__main__.py` used to for the whole
        process — and that shared-session path still needs the explicit rollback:
        without it, an exception this guard did not already know how to translate (a
        raw DBAPI failure, most realistically) leaves that shared session's
        transaction failed, and every later call on it — including an unrelated read
        like `describe_schema` — fails too (`sqlalchemy.exc.PendingRollbackError` in
        production terms, or its underlying `psycopg.errors.InFailedSqlTransaction`
        under the savepoint-based sessions this project's tests use), forever, until
        the process (or, in a test, the fixture) is torn down. Calling `rollback()`
        on a session `_session_scope()` is about to close anyway (the
        `ScopedSessionProvider` path) is harmless — `Session.close()` already
        discards any open transaction — so one guard body serves both providers
        without branching on which kind it received. The trailing
        `except Exception: ...; raise` re-raises the original exception completely
        unchanged — it must not also translate a `KeyError`/`AttributeError` into
        `_as_protocol_error`, the same "guard must not be too wide" property Task 17
        verified about the two narrower `except` clauses above it — it exists only
        to guarantee the rollback runs for literally anything that can come out of
        `fn`, not to add another translated error shape.
        """
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with _session_scope():
                    try:
                        return await fn(*args, **kwargs)
                    except DomainError as exc:
                        context.session.rollback()
                        raise _as_protocol_error(exc) from exc
                    except ValueError as exc:
                        context.session.rollback()
                        raise _as_protocol_error(to_domain_error(exc)) from exc
                    except Exception:
                        context.session.rollback()
                        raise

            return cast(T, async_wrapper)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _session_scope():
                try:
                    return fn(*args, **kwargs)
                except DomainError as exc:
                    context.session.rollback()
                    raise _as_protocol_error(exc) from exc
                except ValueError as exc:
                    context.session.rollback()
                    raise _as_protocol_error(to_domain_error(exc)) from exc
                except Exception:
                    context.session.rollback()
                    raise

        return cast(T, wrapper)

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

    from pigrocrm_mcp.prompts import register_prompts
    from pigrocrm_mcp.tools import register_entity_tools

    register_entity_tools(mcp, context, _guard)
    # §10's four prompts, guarded by the same closure the tools get. A prompt reads the
    # database exactly as a tool does, so it inherits `_session_scope()` and the rollback
    # with it -- there is no second session story for prompts, and there must not be: three
    # of the four open a `REPEATABLE READ` snapshot through `DashboardService`, which is
    # possible only on a session nothing has touched. `ScopedSessionProvider` gives them
    # one; a caller wiring `lambda: shared_session` gets the service's loud `RuntimeError`
    # rather than a briefing whose figures were true at no single instant.
    register_prompts(mcp, context, _guard)

    if gmail_configured(resolved_settings):
        # Conditional, and this is the whole of "absent, not broken": not registered
        # means not listed and not callable. An installation that self-hosts precisely
        # in order not to have Google does not get three tools that answer 409.
        from pigrocrm_mcp.tools import gmail as gmail_tools

        gmail_tools.register(mcp, context, _guard, resolved_settings)

        # Same block, same reason: one Google OAuth client issues both the Gmail grant
        # and the Drive one, so whether Drive diagnosis is available is the same fact as
        # whether Gmail is. `describe_drive_account` costs no quota and exercises no
        # consent -- it is not privileged for the same reason `describe_gmail_account`
        # is not (see `tools/drive.py`'s docstring).
        from pigrocrm_mcp.tools import drive as drive_tools

        drive_tools.register(mcp, context, _guard, resolved_settings)

    if resolved_settings.mcp_full_access:
        # The other half of the switch. `Actor.full_access` (stamped in
        # `PatService.resolve`) decides whether the *service* says yes; this decides
        # whether there is a door at all. Both read the same setting, and
        # `test_mcp_invoice_ban.py` fails if they disagree -- registered tools that all
        # refuse, or capabilities with no way to reach them, are both worse than either
        # honest state.
        #
        # Conditional for the same reason Gmail is: not registered means not listed and
        # not callable. An installation that has not opted in does not get tools answering
        # «vietato», it gets a surface on which they do not exist. The module
        # reads the settings once more for the one tool that also needs a mailbox
        # (`discover_gmail_correspondents`), which is absent without Google exactly as
        # `tools/gmail.py` is.
        from pigrocrm_mcp.tools import privileged as privileged_tools

        privileged_tools.register(mcp, context, _guard, resolved_settings)

        if gmail_configured(resolved_settings):
            # Slice 9C §4.2's three Drive reads, and the only privileged module whose
            # *whole* content needs Google as well as the switch: reading a folder or a
            # file spends the titolare's Drive quota under their OAuth consent, and
            # without a Google client there is no credential to spend it with. So the
            # second condition is expressed here, in the import, rather than as an `if`
            # inside `register` -- unlike `privileged.py`, which is registered by the
            # switch alone and re-reads the settings for its one Gmail tool.
            #
            # Both privileged modules are named in `test_mcp_invoice_ban.py`'s
            # `PRIVILEGED_MODULES`, and that file fails if either is reachable outside
            # this block: the exemption its source scans grant is enumerated in one
            # place and checked, not left to a comment.
            from pigrocrm_mcp.tools import drive_privileged as drive_privileged_tools

            drive_privileged_tools.register(mcp, context, _guard, resolved_settings)
    return mcp
