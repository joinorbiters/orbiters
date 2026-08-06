"""The one rule that cannot be recovered later: core must not depend on adapters."""

import ast
from pathlib import Path

CORE_SRC = Path(__file__).resolve().parents[1] / "src" / "pigrocrm" / "core"
FORBIDDEN_ROOTS = {"pigrocrm_api", "pigrocrm_mcp", "fastapi", "mcp", "starlette"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_never_imports_from_adapters() -> None:
    offenders: list[str] = []
    for path in CORE_SRC.rglob("*.py"):
        bad = _imported_roots(path) & FORBIDDEN_ROOTS
        if bad:
            offenders.append(f"{path.relative_to(CORE_SRC)} imports {sorted(bad)}")
    assert not offenders, (
        "packages/core must not import adapters or web frameworks:\n  " + "\n  ".join(offenders)
    )


def test_core_source_directory_exists() -> None:
    assert CORE_SRC.is_dir(), f"expected core sources at {CORE_SRC}"
