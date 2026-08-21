"""An agent must not be able to issue a fiscal document.

The guarantee is *structural*: the tool is not registered. It is deliberately not a
permission check, because a personal access token inherits its owner's full role and
never expires (residuo R10) -- so a check inside a registered tool is a check an
administrator's token passes, and "give a token to Claude" would mean "let Claude issue
invoices in your name".

A comment saying so protects nothing. These tests read the registration module's AST and
fail if any forbidden operation ever appears as a tool, so the guarantee survives
someone adding one without reading the comment. Slice 4's and slice 6's plans extend the
same list, which is why `FORBIDDEN` is a module-level constant with one name per line
rather than an inline literal.
"""

import ast
from pathlib import Path

import pytest

TOOLS_INIT = (
    Path(__file__).resolve().parents[1] / "src" / "pigrocrm_mcp" / "tools" / "__init__.py"
)

# The four operations that turn a draft into a fiscal fact, or change what one says
# after the fact. Each is reachable over REST by a human with the right role; none is
# reachable by an agent at all.
FORBIDDEN = (
    "issue_invoice",
    "annul_invoice",
    "mark_invoice_transmitted",
    "export_invoice_xml",
)

# The service methods behind them. Listed separately because a future tool could call one
# under an innocuous name -- `finalise_invoice` registering a tool that calls `issue`
# would pass a name check and defeat the point.
FORBIDDEN_SERVICE_CALLS = (
    "issue",
    "annul",
    "mark_transmitted_externally",
    "export_xml",
)


def _module() -> ast.Module:
    return ast.parse(TOOLS_INIT.read_text(encoding="utf-8"), filename=str(TOOLS_INIT))


def _registered_tool_names(module: ast.Module) -> set[str]:
    """Every function carrying an `@mcp.tool()` decorator, at any nesting depth.

    Walks the whole tree rather than the top level: the registrations live inside
    `build_server`'s body, so a top-level-only scan would report nothing and pass
    vacuously -- which is the failure mode this file exists to avoid in the code it
    guards.
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


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_no_tool_is_registered_for_a_fiscal_write(forbidden: str) -> None:
    assert forbidden not in _registered_tool_names(_module()), (
        f"'{forbidden}' e' registrato come tool MCP. Emettere, annullare, marcare come "
        "trasmessa o esportare l'XML di una fattura sono atti fiscali: restano fuori "
        "dalla superficie MCP per costruzione, non per controllo di permessi, perche' "
        "un PAT eredita il ruolo pieno del proprietario e non scade (residuo R10)."
    )


@pytest.mark.parametrize("method", FORBIDDEN_SERVICE_CALLS)
def test_no_registered_tool_calls_a_fiscal_write_under_another_name(method: str) -> None:
    """The name check alone is not enough: a tool called `finalise_invoice` that calls
    `InvoiceService.issue` would pass it. This looks at what the module actually calls."""
    module = _module()
    tool_names = _registered_tool_names(module)
    offenders: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef) or node.name not in tool_names:
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == method
            ):
                offenders.append(node.name)
    assert not offenders, (
        f"il tool {offenders} chiama '.{method}(...)'. Il divieto vale sull'operazione, "
        "non sul nome del tool: rinominarlo non lo rende ammissibile."
    )
