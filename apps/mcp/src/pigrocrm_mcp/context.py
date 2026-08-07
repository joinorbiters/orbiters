from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor

SessionProvider = Callable[[], Session]
ActorProvider = Callable[[], Actor]


@dataclass(frozen=True)
class McpContext:
    """Injected rather than imported, so tests drive the server in-process with a
    rolled-back transaction instead of spawning a subprocess."""

    session_provider: SessionProvider
    actor_provider: ActorProvider

    @property
    def session(self) -> Session:
        return self.session_provider()

    @property
    def actor(self) -> Actor:
        return self.actor_provider()
