"""The one new convention of slice 6, enforced.

Spec §9.3: a service may expose a `*_in_transaction(...)` method that mutates, does not
record, does not commit and does not check authorisation -- and such methods must be
called **only** from `core/automations/`.

Without this test the convention is a comment. `set_stage_in_transaction` skips
`actor.require_write`, so a router calling it eighteen months from now -- because its name
reads like a helper -- would be an authorisation bypass with no error anywhere. The check
is on the *call site*, in the AST, across `packages/core`, `apps/api` and `apps/mcp`.

Three guards on the guard, because a scan that silently stops finding call sites passes
forever and is worse than no scan at all: one asserts the searched roots exist and hold
real modules, one asserts a `*_in_transaction` method is actually defined somewhere (a
guard over an empty set proves nothing), and one feeds the walk an obviously offending
file and requires it to be seen.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SEARCHED_ROOTS = (
    REPO_ROOT / "packages" / "core" / "src" / "pigrocrm" / "core",
    REPO_ROOT / "apps" / "api" / "src" / "pigrocrm_api",
    REPO_ROOT / "apps" / "mcp" / "src" / "pigrocrm_mcp",
)
SUFFIX = "_in_transaction"
# The one directory allowed to call them, as a path fragment rather than a module name so
# a future `core/automations/rules/foo.py` is covered without an edit here.
ALLOWED_FRAGMENT = "core/automations/"


def _calls_with_suffix(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr.endswith(SUFFIX):
            found.append(f"{func.attr} (line {node.lineno})")
    return found


def _definitions_with_suffix(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.endswith(SUFFIX)
    ]


def test_in_transaction_methods_are_called_only_from_core_automations() -> None:
    offenders: list[str] = []
    for root in SEARCHED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            as_posix = path.as_posix()
            if ALLOWED_FRAGMENT in as_posix:
                continue
            calls = _calls_with_suffix(path)
            if calls:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {calls}")
    assert not offenders, (
        "a `*_in_transaction` method mutates without checking authorisation, without "
        "recording and without committing; it may only be called from core/automations/ "
        "(spec §9.3). Offending call sites:\n" + "\n".join(offenders)
    )


def test_the_scan_actually_reads_the_three_packages() -> None:
    """The first guard on the guard: a renamed or moved source tree makes `rglob` yield
    nothing and the assertion above passes over zero files. Each root must exist and hold
    a module this project is known to have."""
    for root in SEARCHED_ROOTS:
        assert root.is_dir(), root
        assert list(root.rglob("*.py")), root
    core, api, mcp = SEARCHED_ROOTS
    assert (core / "deals" / "service.py").exists()
    assert (api / "routers").is_dir()
    assert (mcp / "tools").is_dir()


def test_at_least_one_such_method_exists_so_the_guard_is_not_vacuous() -> None:
    """A guard over an empty set passes forever and proves nothing."""
    defined: list[str] = []
    for path in sorted(SEARCHED_ROOTS[0].rglob("*.py")):
        defined.extend(_definitions_with_suffix(path))
    assert "set_stage_in_transaction" in defined, defined


def test_the_guard_catches_a_call_from_outside(tmp_path: Path) -> None:
    """The guard proven to catch what it claims to, in the same style as the
    import-direction tests in test_architecture.py."""
    offending = tmp_path / "router.py"
    offending.write_text(
        "def endpoint(session, deal, stage):\n"
        "    DealService(session).set_stage_in_transaction(deal, stage)\n",
        encoding="utf-8",
    )
    assert _calls_with_suffix(offending), "the AST walk failed to see an obvious call"
