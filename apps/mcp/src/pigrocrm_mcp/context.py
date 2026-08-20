from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

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
    `get_storage` dependency already establishes (`pigrocrm_api.deps`), and unlike
    the session -- which R1 (see `server.py`) deliberately keeps as one shared,
    long-lived instance for a reason out of this slice's scope -- there is no
    equivalent reason for storage to be re-resolved per call.
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
