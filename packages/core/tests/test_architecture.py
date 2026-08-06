"""The one rule that cannot be recovered later: core must not depend on adapters.

This is an allowlist, not a denylist. packages/core may import:
  - the standard library,
  - itself (the ``pigrocrm`` namespace),
  - whatever packages/core/pyproject.toml actually declares under
    ``[project].dependencies``.

Anything else - an adapter package such as pigrocrm_api or pigrocrm_mcp, a web
framework, a dependency only the adapters declare - fails the test. This means
adding a dependency to apps/api or apps/mcp never requires touching this file,
while importing something into core that core does not declare fails on its
own, without anyone having to remember to update a denylist by hand.

Known, accepted limitation: dynamic imports are only caught when the module
name is a string literal, e.g. ``importlib.import_module("fastapi")`` or
``__import__("fastapi")``. ``importlib.import_module(some_variable)`` cannot be
resolved statically and slips through - see
test_guard_known_limitation_cannot_catch_dynamic_import_via_variable below,
which demonstrates the gap with a real example instead of just asserting it
away in prose.
"""

import ast
import re
import sys
import tomllib
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = CORE_ROOT / "src" / "pigrocrm" / "core"

# Distribution name (as written in packages/core/pyproject.toml's
# [project].dependencies) -> importable module root, for the cases where they
# differ. Most distributions import as themselves ("-" becomes "_"); these
# do not and must be spelled out explicitly rather than guessed.
DIST_TO_MODULE_OVERRIDES: dict[str, str] = {
    "psycopg": "psycopg",  # extras such as "[binary]" are stripped before lookup
    "argon2-cffi": "argon2",
    "pyjwt": "jwt",
    "uuid-utils": "uuid_utils",
    "pydantic-settings": "pydantic_settings",
}

# PEP 508 requirement strings look like "name[extra]==1.2.3" or "name>=1.0";
# grab the leading name (letters, digits, ".", "_", "-") and stop at the
# first character that starts an extras marker, version specifier, or marker.
_DEP_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


def _dependency_name(requirement: str) -> str:
    """Bare distribution name from a PEP 508 requirement string.

    "psycopg[binary]==3.3.4" -> "psycopg"; "sqlalchemy==2.0.51" -> "sqlalchemy".
    """
    match = _DEP_NAME_RE.match(requirement.strip())
    if not match:
        raise ValueError(f"cannot parse dependency requirement: {requirement!r}")
    return match.group(0)


def _module_root(requirement: str) -> str:
    dist = _dependency_name(requirement)
    return DIST_TO_MODULE_OVERRIDES.get(dist, dist.replace("-", "_"))


def _declared_dependency_roots() -> set[str]:
    data = tomllib.loads((CORE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies: list[str] = data["project"]["dependencies"]
    return {_module_root(dep) for dep in dependencies}


ALLOWED_ROOTS: set[str] = _declared_dependency_roots() | set(sys.stdlib_module_names) | {"pigrocrm"}


def _literal_str_arg(call: ast.Call) -> str | None:
    """The first positional argument of `call`, if it is a plain string literal."""
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _is_dynamic_import_call(node: ast.Call) -> bool:
    """True for `importlib.import_module(...)` (any alias) or `__import__(...)`."""
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "import_module":
        return True
    return isinstance(func, ast.Name) and func.id == "__import__"


def _imported_roots(path: Path) -> set[str]:
    """Every top-level module root `path` imports, statically or dynamically-by-literal."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and _is_dynamic_import_call(node):
            literal = _literal_str_arg(node)
            if literal is not None:
                roots.add(literal.split(".")[0])
    return roots


def _offenders_in(source_dir: Path) -> list[str]:
    """One message per .py file under source_dir that imports a root outside ALLOWED_ROOTS."""
    offenders: list[str] = []
    for path in source_dir.rglob("*.py"):
        bad = _imported_roots(path) - ALLOWED_ROOTS
        if bad:
            offenders.append(
                f"{path.relative_to(source_dir)} imports {sorted(bad)} "
                "(not declared in packages/core/pyproject.toml)"
            )
    return offenders


def test_core_never_imports_from_adapters() -> None:
    offenders = _offenders_in(CORE_SRC)
    assert not offenders, (
        "packages/core may only import the stdlib, pigrocrm, and dependencies declared "
        "in packages/core/pyproject.toml:\n  " + "\n  ".join(offenders)
    )


def test_core_source_directory_exists() -> None:
    assert CORE_SRC.is_dir(), f"expected core sources at {CORE_SRC}"


# --- The guard proven to actually catch what it claims to, not just written. ---


def test_guard_catches_static_adapter_import(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import pigrocrm_api\n", encoding="utf-8")
    offenders = _offenders_in(tmp_path)
    assert offenders and "pigrocrm_api" in offenders[0]


def test_guard_catches_dynamic_import_with_literal_string(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        'import importlib\nimportlib.import_module("fastapi")\n', encoding="utf-8"
    )
    offenders = _offenders_in(tmp_path)
    assert offenders and "fastapi" in offenders[0]


def test_guard_catches_dunder_import_with_literal_string(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text('__import__("mcp")\n', encoding="utf-8")
    offenders = _offenders_in(tmp_path)
    assert offenders and "mcp" in offenders[0]


def test_guard_allows_stdlib_pigrocrm_and_declared_dependencies(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text(
        "import json\nimport sqlalchemy\nimport uuid_utils\nfrom pigrocrm.core import qualcosa\n",
        encoding="utf-8",
    )
    assert _offenders_in(tmp_path) == []


def test_guard_known_limitation_cannot_catch_dynamic_import_via_variable(
    tmp_path: Path,
) -> None:
    """Documents the accepted gap: a non-literal argument can't be resolved statically."""
    (tmp_path / "sneaky.py").write_text(
        'import importlib\n_name = "fastapi"\nimportlib.import_module(_name)\n',
        encoding="utf-8",
    )
    assert _offenders_in(tmp_path) == []
