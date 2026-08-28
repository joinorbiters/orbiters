"""An agent must not be able to issue a fiscal document, nor touch the handful of
slice-4 operations that are closer to configuration or to rewriting the past than to
recording an entity.

The guarantee is *structural*: the tool is not registered. It is deliberately not a
permission check, because a personal access token inherits its owner's full role and
never expires (residuo R10) -- so a check inside a registered tool is a check an
administrator's token passes, and "give a token to Claude" would mean "let Claude issue
invoices in your name", or recalculate what a quarter's work was worth.

A comment saying so protects nothing. These tests read every module under `tools/` and
fail if any forbidden operation ever appears as a tool, or is called under another name,
so the guarantee survives someone adding one without reading the comment. Slice 4 and
slice 6 extend the same two lists rather than writing a parallel mechanism -- which is
why `FORBIDDEN`/`FORBIDDEN_SERVICE_CALLS` are module-level constants with one name per
line rather than inline literals, and why the source scan below covers every file in
`tools/`, not only `tools/__init__.py`: slice 4's tool call-throughs live in their own
module (`tools/timetracking.py`, mirroring `tools/invoices.py`), and a registered tool
that called a same-named wrapper in that module which itself called a forbidden service
method would leave no trace in `tools/__init__.py` alone.
"""

import ast
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "src" / "pigrocrm_mcp" / "tools"
TOOLS_INIT = TOOLS_DIR / "__init__.py"

# Sixteen operations: the five fiscal ones that turn a draft into a fiscal fact or
# change what one says after the fact, and the eleven that are closer to configuration
# or to rewriting the past than to recording an entity. Each is reachable over REST by a
# human with the right role; none is reachable by an agent at all. `bind_time_to_invoice`
# and `get_fiscal_estimate` belong to `AnalyticsService`, which does not exist until plan
# 4B -- declared here regardless, because the ban is a decision made now and plan 4B must
# not have to touch this list to honour it.
#
# Two of the sixteen were added after an audit found the repo stating this policy twice
# and the two statements disagreeing:
#
#   * `update_fiscal_profile` is one of the *four* names slice 3 §11 actually banned
#     (`issue_invoice`, `annul_invoice`, `mark_transmitted_externally`,
#     `update_fiscal_profile`); this list dropped it and put `export_invoice_xml` -- a
#     real, correct addition -- in its place, while `tools/invoices.py` went on declaring
#     it forbidden in a table nothing imported. That row decides the VAT rate, the
#     natura, the bollo and the normative reference printed on every invoice line: it is
#     the configuration this ban exists for, not an exception to it.
#   * `unarchive_cost_category` is `archive_cost_category` in the other direction, and
#     the same decision about which categories the CRM offers. Its absence from slice 4
#     §11's list of ten is an omission rather than a distinction -- there is no reading
#     under which creating, renaming and archiving a category are configuration and
#     bringing one back is not.
FORBIDDEN = (
    "issue_invoice",
    "annul_invoice",
    "mark_invoice_transmitted",
    "export_invoice_xml",
    "update_fiscal_profile",
    "recalculate_rates",
    "update_user_rates",
    "update_deal_rate",
    "create_cost_category",
    "update_cost_category",
    "archive_cost_category",
    "unarchive_cost_category",
    "close_period",
    "reopen_period",
    "bind_time_to_invoice",
    "get_fiscal_estimate",
)

# The service methods behind them. Listed separately because a future tool could call one
# under an innocuous name -- `finalise_invoice` registering a tool that calls `issue`
# would pass a name check and defeat the point. Fifteen, not sixteen: the sixteenth is
# `FiscalProfileService.upsert`, which a bare name cannot express and which is banned by
# `FORBIDDEN_QUALIFIED_CALLS` below.
FORBIDDEN_SERVICE_CALLS = (
    "issue",
    "annul",
    "mark_transmitted_externally",
    "export_xml",
    "recalculate_rates",
    "update_user_rates",
    "update_deal_rate",
    "create_cost_category",
    "update_cost_category",
    "archive_cost_category",
    "unarchive_cost_category",
    "close_period",
    "reopen_period",
    "bind_time_to_invoice",
    "get_fiscal_estimate",
)

# The bans a bare method name cannot express, because the name is not the operation.
# `update_fiscal_profile` is `FiscalProfileService.upsert`, and `upsert` is exactly the
# kind of name a second service already carries: `EmitterProfileService.upsert` writes
# the issuer's identity, and `EmitterProfileService.get` is *on* the MCP surface -- the
# PDF header needs it for every role. Putting "upsert" in the tuple above would ban the
# substring, so any call spelled that way, on any service, would fail this file with a
# message about the fiscal profile. A ban on a name is not a ban on an operation, and the
# fifteen names above are safe only because each of them happens to be unique; this one
# is not, so it names its receiver and `_receivers_of` resolves it.
FORBIDDEN_QUALIFIED_CALLS = (("FiscalProfileService", "upsert"),)

_REASON = (
    "e' un'operazione esclusa dalla superficie MCP per costruzione (slice 3 §11 per "
    "gli atti fiscali e per il profilo fiscale, slice 4 §11 per le tariffe, le "
    "categorie di costo e le chiusure di periodo), non per controllo di permessi: un "
    "PAT eredita il ruolo pieno del proprietario e non scade (residuo R10), quindi "
    "l'assenza del tool e' l'unico meccanismo che regge."
)


def _module(path: Path = TOOLS_INIT) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _registered_tool_names(module: ast.Module) -> set[str]:
    """Every function carrying an `@mcp.tool()` decorator, at any nesting depth.

    Walks the whole tree rather than the top level: the registrations live inside
    `build_server`'s body, so a top-level-only scan would report nothing and pass
    vacuously -- which is the failure mode this file exists to avoid in the code it
    guards. Scoped to `tools/__init__.py` deliberately: `@mcp.tool()` decorators exist
    only there -- `tools/invoices.py` and `tools/timetracking.py` are plain modules of
    call-through functions with no decorator of their own -- so this is the one file
    where "is a name registered as a tool" can even be asked.
    """
    names: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                names.add(node.name)
    return names


def _tools_source(base: Path = TOOLS_DIR) -> str:
    """Every `.py` file under `tools/`, concatenated.

    Unlike `_registered_tool_names`, this deliberately is not scoped to
    `tools/__init__.py`: the actual call into a service lives one file over, in the
    domain-specific module a registered tool calls through (`tools/invoices.py`,
    `tools/timetracking.py`, ...). A forbidden method reached only from there --
    directly, or through a same-named wrapper function called under a different tool
    name -- must fail exactly as if it were called inline in `tools/__init__.py`
    itself; scanning the whole package is what makes that true regardless of which
    file the call physically sits in.
    """
    return "\n".join(path.read_text(encoding="utf-8") for path in base.rglob("*.py"))


def _receivers_of(method: str, base: Path = TOOLS_DIR) -> list[str | None]:
    """For every call spelled `.method(` anywhere under `base`, the service class it
    lands on -- or `None` where this cannot tell.

    Exists for `FORBIDDEN_QUALIFIED_CALLS`, and only for it: the substring scan below is
    the right instrument for a method name that belongs to exactly one service, and the
    wrong one for `upsert`. Resolves the three call shapes this package actually uses --
    `ServiceClass(context.session).m(...)`, `svc = ServiceClass(...)` then `svc.m(...)`,
    and the module-private factories (`_invoices(context) -> InvoiceService`) that
    `tools/invoices.py` and `tools/documents.py` use -- recognising a service by this
    codebase's own naming rule, a class whose name ends in `Service`, so that this file
    stays readable without importing anything from `packages/core`.

    An unresolved receiver is reported as `None` and counted as an offence by the caller.
    That is the whole point of returning `None` rather than dropping the call: "we could
    not work out whose `upsert` this is" must not read as "it is not the forbidden one".
    A ban that fails open is not a ban.
    """
    receivers: list[str | None] = []
    for path in sorted(base.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        factories: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                returns = node.returns
                if isinstance(returns, ast.Name) and returns.id.endswith("Service"):
                    factories[node.name] = returns.id

        def produced(func: ast.expr, factories: dict[str, str] = factories) -> str | None:
            if not isinstance(func, ast.Name):
                return None
            return func.id if func.id.endswith("Service") else factories.get(func.id)

        bindings: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                owner = produced(node.value.func)
                if owner is not None:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            bindings[target.id] = owner

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != method:
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Call):
                receivers.append(produced(receiver.func))
            elif isinstance(receiver, ast.Name):
                receivers.append(bindings.get(receiver.id))
            else:
                receivers.append(None)
    return receivers


def test_the_ast_walk_actually_finds_the_registered_tools() -> None:
    """Guards the guard. If `_registered_tool_names` returned an empty set -- because the
    decorator spelling changed, or because the registrations moved -- every ban test
    below would pass while checking nothing. Anchored on tools that exist today and on a
    plausible count, so a silent break is a failure and not a green run."""
    names = _registered_tool_names(_module())
    assert "list_invoices" in names
    assert "get_invoice" in names
    assert "create_customer" in names
    assert len(names) > 20


def test_the_source_scan_actually_reads_more_than_one_file() -> None:
    """Guards the *other* guard. If `_tools_source` only ever returned
    `tools/__init__.py`'s own text -- because `rglob` found nothing, or `TOOLS_DIR` was
    pointed at the wrong directory -- `test_no_registered_tool_calls_a_fiscal_write_
    under_another_name` would silently stop seeing `tools/invoices.py` and
    `tools/timetracking.py` at all, which is exactly the gap the whole-package scan
    exists to close."""
    source = _tools_source()
    assert "def search(" in source  # tools/invoices.py
    assert "def log_time(" in source  # tools/timetracking.py


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_no_tool_is_registered_for_a_forbidden_operation(forbidden: str) -> None:
    assert forbidden not in _registered_tool_names(_module()), (
        f"'{forbidden}' e' registrato come tool MCP, ma {_REASON}"
    )


@pytest.mark.parametrize("method", FORBIDDEN_SERVICE_CALLS)
def test_no_tool_reaches_a_forbidden_operation_under_another_name(method: str) -> None:
    """The name check alone is not enough: a tool called `finalise_paperwork` that calls
    `.issue(...)`, or one called `tidy_up_rates` whose own call-through wrapper in
    `tools/timetracking.py` calls `.recalculate_rates(...)`, would both pass it. This
    looks at what the whole `tools/` package actually calls, not at any one tool's own
    name."""
    offenders_in_source = f".{method}(" in _tools_source()
    assert not offenders_in_source, (
        f"'.{method}(' compare in qualche modulo sotto tools/, ma quell'operazione "
        f"{_REASON} Il divieto vale sulla chiamata, non sul nome del tool che vi "
        "arriva: rinominare il tool o spostare la chiamata in un altro modulo non la "
        "rende ammissibile."
    )


def test_the_qualified_scan_tells_two_services_with_the_same_method_apart(tmp_path: Path) -> None:
    """Guards the guard, on the one property that makes it worth having. If
    `_receivers_of` collapsed to "some `.upsert(` exists", banning
    `FiscalProfileService.upsert` would also ban `EmitterProfileService.upsert` -- and a
    future tool for the issuer's own identity would fail the build with a message about
    the fiscal regime, which is how a policy stops being believed."""
    (tmp_path / "m.py").write_text(
        "def a(context):\n"
        "    return EmitterProfileService(context.session).upsert(data, context.actor)\n"
        "\n"
        "def b(context):\n"
        "    return FiscalProfileService(context.session).upsert(data, context.actor)\n",
        encoding="utf-8",
    )
    assert sorted(str(r) for r in _receivers_of("upsert", tmp_path)) == [
        "EmitterProfileService",
        "FiscalProfileService",
    ]


def test_the_qualified_scan_fails_closed_on_a_receiver_it_cannot_resolve(tmp_path: Path) -> None:
    """The other half, and the one that decides whether this mechanism is a ban or a
    suggestion: a call whose receiver the walk cannot attribute to a class is reported as
    unresolved, and the ban test below treats unresolved as forbidden. Anything else
    would let `some_container.fiscal.upsert(...)` through on the grounds that nobody
    could prove what it was."""
    (tmp_path / "m.py").write_text(
        "def a(context):\n    return context.services.fiscal.upsert(data)\n", encoding="utf-8"
    )
    assert _receivers_of("upsert", tmp_path) == [None]


@pytest.mark.parametrize(("service", "method"), FORBIDDEN_QUALIFIED_CALLS)
def test_no_tool_reaches_a_forbidden_operation_on_the_service_that_owns_it(
    service: str, method: str
) -> None:
    """The qualified half of `test_no_tool_reaches_a_forbidden_operation_under_another_
    name`. Same guarantee, expressed against the receiver instead of the bare name,
    because the bare name would either miss the operation or ban an unrelated one."""
    offenders = [
        owner or "un ricevitore non risolvibile"
        for owner in _receivers_of(method)
        if owner is None or owner == service
    ]
    assert not offenders, (
        f"'.{method}(' e' chiamato su {offenders} da qualche modulo sotto tools/, ma "
        f"'{service}.{method}' {_REASON} Il divieto vale su questa coppia "
        "servizio/metodo: un ricevitore che questo controllo non sa attribuire conta "
        "come violazione, perche' un divieto che si arrende all'ambiguita' non e' un "
        "divieto."
    )
