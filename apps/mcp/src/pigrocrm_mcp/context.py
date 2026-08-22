import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from pigrocrm.core.actor import Actor
from pigrocrm.core.storage import DocumentStorage

SessionProvider = Callable[[], Session]
ActorProvider = Callable[[], Actor]


@dataclass(frozen=True)
class McpContext:
    """Injected rather than imported, so tests drive the server in-process with a
    rolled-back transaction instead of spawning a subprocess.

    `storage` is a plain value, not a provider like `session_provider`/
    `actor_provider`: one backend per process is exactly what the API's own
    `get_storage` dependency already establishes (`pigrocrm_api.deps`). Unlike the
    session, there is no equivalent reason for storage to be re-resolved per call --
    see `ScopedSessionProvider` below for why the session, unlike storage, now needs
    one instance per logical call (Task 4A-1, residual R1).
    """

    session_provider: SessionProvider
    actor_provider: ActorProvider
    storage: DocumentStorage

    @property
    def session(self) -> Session:
        return self.session_provider()

    @property
    def actor(self) -> Actor:
        return self.actor_provider()


_CURRENT_SESSION: contextvars.ContextVar[Session] = contextvars.ContextVar("mcp_session")


class ScopedSessionProvider:
    """One `Session` per logical MCP call, not one per process.

    Closes residual R1: the process previously built a single `Session` and passed
    `lambda: session` to `build_server`, shared by every tool call for the whole
    process lifetime. The SDK dispatches sync tool calls concurrently (a thread
    pool) and coroutine tools on an event loop, and ten concurrent writes against
    that one shared `Session` were measured, at the time, as zero successes and
    zero rows written -- unusable for `log_time` (slice 4's `log_time` is a write
    tool and the centre of its agentic surface).

    `contextvars`, not `threading.local`: a `ContextVar` is the only primitive that
    is correct for both dispatch styles above -- each task and each thread sees its
    own binding, and `Context.run` copying does not leak one call's session into
    another's.

    `__call__` refuses outside a scope instead of quietly opening a session. A
    session nobody closes is the failure this class exists to remove, and returning
    one from an unscoped read would reintroduce exactly that leak.
    """

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def __call__(self) -> Session:
        try:
            return _CURRENT_SESSION.get()
        except LookupError as exc:
            raise RuntimeError(
                "no MCP session scope is active: every tool and resource must run "
                "inside ScopedSessionProvider.scope()"
            ) from exc

    @contextmanager
    def scope(self) -> Iterator[Session]:
        session = self._factory()
        token = _CURRENT_SESSION.set(session)
        try:
            yield session
        finally:
            _CURRENT_SESSION.reset(token)
            session.close()
