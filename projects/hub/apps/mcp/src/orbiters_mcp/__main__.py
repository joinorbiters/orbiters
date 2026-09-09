from orbiters_core.config import get_settings
from orbiters_core.db import create_engine_from_settings, session_factory
from orbiters_mcp.server import build_server


def main() -> int:
    engine = create_engine_from_settings(get_settings())
    build_server(session_factory(engine)).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
