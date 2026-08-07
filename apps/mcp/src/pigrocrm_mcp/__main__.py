import os
import sys

from pigrocrm.core.auth.pat_service import PatService
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.errors import DomainError
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
    factory = session_factory(engine)
    session = factory()

    try:
        actor = PatService(session).resolve(token)
    except DomainError as exc:
        print(f"Token non valido: {exc.message}", file=sys.stderr)
        return 1

    build_server(lambda: session, lambda: actor).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
