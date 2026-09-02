"""**Criterion 11**, the two clauses of spec §3.

`DashboardService` is a composition service: it resolves authorisation, opens a
transaction, calls services and repositories, and assembles the result. It contains no
arithmetic. That sentence is worth nothing as a comment and everything as a build failure,
because the alternative -- a dashboard that computes a margin its own way -- is the second
source of truth §1 is about, and on a margin nobody notices.

Both clauses are decidable on the AST **without type inference**, which is why they are
these two clauses and not "no arithmetic on money": a rule needing to know that a variable
holds a `Decimal` is not a rule a test can apply.

  1. no module under `core/dashboard/` imports `Decimal`  -- except `schemas.py`, which
     imports it to *type* its fields and performs no arithmetic;
  2. no module under `core/dashboard/` contains a `BinOp` node with `*`, `/` or `-`, and
     the exemption list for this clause is **empty**.

A composition service that cannot subtract cannot invent a margin.

A third clause is here that the brief did not name, and it closes the obvious way round the
first two: `sum(...)`, `round(...)` and anything imported from `pigrocrm.core.money` produce
a figure with no `BinOp` and no `Decimal` in sight. §3's sentence is "no figure is born in
`core/dashboard/`", not "no operator appears there", so the total belongs in the
repository of the table it counts either way.

**What is *not* here.** The ban on `date.today()`/`datetime.now(...).date()` is enforced by
`test_clock.py`, where Task B1 put it after finding that this task's brief -- which B1's own
brief promised would carry it -- is about the dashboard's arithmetic instead. That scan
covers all three source trees with `db/clock.py` as its sole exemption, it proves its own
matcher against both banned shapes, and it stays there. One rule, one scan: a second copy
here would be a second thing to keep in step, and the two would disagree the first time
either was edited.
"""

import ast
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = CORE_ROOT / "src" / "pigrocrm" / "core" / "dashboard"

ARITHMETIC_OPS = (ast.Mult, ast.Div, ast.FloorDiv, ast.Sub, ast.Mod, ast.Pow)

# `schemas.py` imports `Decimal` to annotate its fields. Declaring a field's type is not
# arithmetic, and clause 1 exists to forbid arithmetic. Every other module in the package
# is covered.
DECIMAL_IMPORT_EXEMPT: frozenset[str] = frozenset({"schemas.py"})

# Clause 2 has **no** exemptions, and this emptiness is itself asserted below. A `BinOp`
# with `-` in a dashboard module is either a figure being derived -- forbidden -- or a date
# offset, which belongs in `db/clock.py` where the other date arithmetic already lives.
# Keeping the list empty is what stops the rule degrading one "harmless" entry at a time.
BINOP_EXEMPT: frozenset[str] = frozenset()

# Clause 3: the two builtins that produce a figure without an operator, and the module whose
# whole purpose is to produce one. `round_money`, `sum_money` and `percentage_of` are right
# and necessary -- in the repository that owns the rows, which is where §3 puts them.
FIGURE_PRODUCING_CALLS = ("sum", "round")
FIGURE_PRODUCING_MODULE = "pigrocrm.core.money"


def _modules() -> list[Path]:
    return sorted(DASHBOARD_ROOT.rglob("*.py"))


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports_decimal(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "decimal"
            and any(alias.name == "Decimal" for alias in node.names)
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name in ("decimal", "decimal.Decimal") for alias in node.names
        ):
            return True
    return False


def _arithmetic_binops(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ARITHMETIC_OPS):
            found.append((type(node.op).__name__, node.lineno))
        # `x -= 1` and `x *= 2` are AugAssign, not BinOp, and would slip through a
        # BinOp-only walk. Same rule, same reason.
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ARITHMETIC_OPS):
            found.append((f"Aug{type(node.op).__name__}", node.lineno))
    return found


def _figure_producers(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FIGURE_PRODUCING_CALLS
        ):
            found.append((f"{node.func.id}()", node.lineno))
        if isinstance(node, ast.ImportFrom) and node.module == FIGURE_PRODUCING_MODULE:
            found.append((FIGURE_PRODUCING_MODULE, node.lineno))
        if isinstance(node, ast.Import):
            found.extend(
                (alias.name, node.lineno)
                for alias in node.names
                if alias.name == FIGURE_PRODUCING_MODULE
            )
    return found


# --- guards on the guard -----------------------------------------------------------


def test_the_dashboard_package_exists_so_this_file_is_not_vacuous() -> None:
    """A guard over an empty directory passes forever and proves nothing."""
    assert DASHBOARD_ROOT.is_dir(), DASHBOARD_ROOT
    modules = _modules()
    assert len(modules) >= 3, [p.name for p in modules]
    assert (DASHBOARD_ROOT / "service.py").exists()


def test_the_guard_catches_an_import() -> None:
    """The guard proven to catch what it claims to, in the same style as the
    import-direction tests in test_architecture.py."""
    assert _imports_decimal(ast.parse("from decimal import Decimal\nx = Decimal('1')\n"))
    assert _imports_decimal(ast.parse("from decimal import Decimal as D\n"))
    assert _imports_decimal(ast.parse("import decimal\n"))
    assert not _imports_decimal(ast.parse("from datetime import date\n"))


def test_the_guard_catches_each_forbidden_operator() -> None:
    for source in (
        "margine = ricavi - costi\n",
        "quota = parte / totale\n",
        "peso = valore * probabilita\n",
        "resto = totale % rate\n",
        "totale -= sconto\n",
        "totale *= 2\n",
    ):
        assert _arithmetic_binops(ast.parse(source)), source


def test_addition_is_allowed_because_it_is_not_the_defect() -> None:
    """`+` is not on the list, deliberately: string and list concatenation are `Add` nodes
    and are everywhere in ordinary code, while the defect §3 is about -- deriving a margin,
    a rate or a share -- needs `-`, `/` or `*`. A rule that also banned `+` would be
    unenforceable and would be turned off."""
    assert not _arithmetic_binops(ast.parse("etichetta = 'a' + 'b'\n"))


def test_the_guard_catches_a_figure_produced_without_an_operator() -> None:
    """Clause 3's matcher, proven the same way. Each of these computes a total inside the
    dashboard package while containing no `BinOp` and importing no `Decimal`, which is why
    the first two clauses on their own are not the whole of §3."""
    for source in (
        "totale = sum(riga.numero for riga in righe)\n",
        "arrotondato = round(valore, 2)\n",
        "from pigrocrm.core.money import sum_money\n",
        "import pigrocrm.core.money\n",
    ):
        assert _figure_producers(ast.parse(source)), source
    assert not _figure_producers(ast.parse("from pigrocrm.core.db import window_from\n"))


# --- the claim ---------------------------------------------------------------------


def test_no_dashboard_module_imports_decimal() -> None:
    offenders: list[str] = []
    for path in _modules():
        if path.name in DECIMAL_IMPORT_EXEMPT:
            continue
        if _imports_decimal(_parse(path)):
            offenders.append(path.name)
    assert not offenders, (
        "a dashboard module imported Decimal. Spec §3: every figure is either returned "
        "verbatim by the service that owns the data, or a single COUNT/SUM in that table's "
        "repository. If a derived figure is needed, it belongs to the service that owns "
        f"the data it derives from. Offenders: {offenders}"
    )


def test_no_dashboard_module_contains_a_multiplication_division_or_subtraction() -> None:
    offenders: list[str] = []
    for path in _modules():
        if path.name in BINOP_EXEMPT:
            continue
        found = _arithmetic_binops(_parse(path))
        if found:
            offenders.append(f"{path.name}: {found}")
    assert not offenders, (
        "a dashboard module contains arithmetic. A composition service that cannot "
        "subtract cannot invent a margin (spec §3). Date offsets belong in db/clock.py; "
        f"derived figures belong to the owning service. Offenders: {offenders}"
    )


def test_no_dashboard_module_produces_a_figure_without_an_operator() -> None:
    offenders: list[str] = []
    for path in _modules():
        found = _figure_producers(_parse(path))
        if found:
            offenders.append(f"{path.name}: {found}")
    assert not offenders, (
        "a dashboard module computes a total. §3's sentence is 'no figure is born in "
        "core/dashboard/', and `sum(...)`, `round(...)` and `pigrocrm.core.money` are how "
        "one is born without tripping the operator clause. The total belongs in the "
        f"repository of the table it counts. Offenders: {offenders}"
    )


def test_the_binop_exemption_list_is_empty() -> None:
    """Spec §3 requires it, in those words: "la lista delle eccezioni è vuota". An
    exemption list that is allowed to grow is a rule that degrades one harmless-looking
    entry at a time, and each entry is individually defensible."""
    assert not BINOP_EXEMPT, f"the exemption list must stay empty: {sorted(BINOP_EXEMPT)}"


def test_the_decimal_exemption_is_exactly_schemas() -> None:
    assert sorted(DECIMAL_IMPORT_EXEMPT) == ["schemas.py"]


def test_the_exempt_module_is_the_one_that_only_declares_types() -> None:
    """The exemption is about declaration, not about a filename.

    `schemas.py` is exempt from clause 1 because it types fields; if it ever grew a `*`,
    `/` or `-` the exemption would be covering computation instead, and clause 2 -- which
    exempts nothing -- would catch it. Asserted here so the two clauses are visibly one
    argument rather than two lists that happen to differ.
    """
    schemas = DASHBOARD_ROOT / "schemas.py"
    assert schemas.name in DECIMAL_IMPORT_EXEMPT
    assert _imports_decimal(_parse(schemas))
    assert not _arithmetic_binops(_parse(schemas))
