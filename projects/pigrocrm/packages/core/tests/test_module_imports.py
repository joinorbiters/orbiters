"""Every module under `pigrocrm.core` must import cleanly.

This exists because of a real bug: a service class had a method named `list`, and a
different method defined further down had a bare `-> list[FieldSpec]` return
annotation. Inside a class body, a `def` statement rebinds its name in the *class*
namespace, and annotations are evaluated eagerly (nothing in this codebase defers them
with `from __future__ import annotations`) by looking the name up in that same
namespace first. Once `def list` had executed, `list` in the class body pointed at
that method, not the builtin -- so the later method's own annotation resolved to it
and blew up at import time with `TypeError: 'function' object is not subscriptable`.

A source-level comment warning "don't reorder this" only protects against the exact
edit someone imagines when they write the comment. The next person to add a method
below `list` -- in this class, or in a class in a domain that does not exist yet --
will not go looking for that comment. Actually importing every module is the only
check that catches the whole class of error, in every domain, forever, instead of
relying on anyone reading a warning first.
"""

import importlib
from pathlib import Path
from types import ModuleType

import pytest

import pigrocrm.core

CORE_PACKAGE = pigrocrm.core


def _module_names(package: ModuleType) -> list[str]:
    """Every module and subpackage dotted name under `package`, discovered by walking
    the filesystem rather than with `pkgutil.walk_packages`.

    `walk_packages` has to *import* each package along the way to read its `__path__`
    and recurse into it -- so a package whose own `__init__.py` fails to import (e.g.
    because it imports the very module with the bug) raises straight out of the
    enumeration step, before the per-module try/except below gets a chance to run.
    That is precisely the failure this test exists to catch, so enumeration here does
    not import anything at all: it only reads file paths and turns them into dotted
    names, deferring every import to `_import_failures`, where it is guarded.
    """
    root = Path(package.__path__[0])
    names = [package.__name__]
    for path in sorted(root.rglob("*.py")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            names.append(".".join([package.__name__, *parts]))
    return names


def _import_failures(package: ModuleType) -> list[str]:
    failures: list[str] = []
    for name in _module_names(package):
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - any import-time failure is the point
            failures.append(f"{name}: {exc!r}")
    return failures


def test_every_module_under_core_imports_cleanly() -> None:
    failures = _import_failures(CORE_PACKAGE)
    assert not failures, "these modules raised at import time:\n  " + "\n  ".join(failures)


def test_the_guard_above_actually_detects_a_shadowed_builtin_annotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the guard is not a no-op: a throwaway package reproducing the exact
    shape of the original bug (a `list` method followed by a method with a bare
    `list[...]` annotation, in a submodule -- not the package's own `__init__.py`, to
    mirror the real bug's shape exactly) must fail this style of check. Built under
    `tmp_path` so this never touches real source on disk."""
    package_dir = tmp_path / "shadow_bug_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "broken.py").write_text(
        "class Broken:\n"
        "    def list(self) -> list[int]:\n"
        "        return []\n"
        "\n"
        "    def specs_for(self) -> list[str]:\n"
        "        return []\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    import shadow_bug_pkg

    failures = _import_failures(shadow_bug_pkg)

    assert failures, "the throwaway package should have reproduced the shadowing bug"
    assert any("not subscriptable" in failure for failure in failures), failures
    assert any(failure.startswith("shadow_bug_pkg.broken:") for failure in failures), failures
