import os
import sys

from pigrocrm.core.auth.pat_service import PatService
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.errors import DomainError
from pigrocrm_mcp.context import ScopedSessionProvider
from pigrocrm_mcp.server import build_server

PAT_ENV_VAR = "PIGROCRM_TOKEN"


def main() -> int:
    token = os.environ.get(PAT_ENV_VAR)
    if not token:
        print(
            f"{PAT_ENV_VAR} non impostato. Genera un token dalla UI in Impostazioni → Token.",
            file=sys.stderr,
        )
        return 1

    engine = create_engine_from_settings(get_settings())
    provider = ScopedSessionProvider(session_factory(engine))

    # The PAT is resolved once, at start-up, in its own short-lived session: the
    # actor does not change for the life of the process, and resolving it inside a
    # per-call scope would hit the database on every tool call for an answer that
    # cannot have changed.
    with provider.scope() as bootstrap:
        try:
            actor = PatService(bootstrap).resolve(token)
        except DomainError as exc:
            print(f"Token non valido: {exc.message}", file=sys.stderr)
            return 1

    build_server(provider, lambda: actor).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
