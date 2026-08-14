"""Walk the parsed tree, escaping each value for the context its node recorded.

The output is *compiled Markdown*, not a PDF: Pandoc and Typst are somebody else's
job (`pigrocrm.core.render.pdf`, not built yet). Keeping this module free of I/O is
what lets the adversarial escaping cases be tested as pure string comparisons, with
no container, no subprocess and no PDF to parse.

Two ways to get this specific module wrong that no test of `escaping.py` or
`parser.py` alone can catch, because both of those modules are correct on their own
terms and stay that way even if this one misuses them:

1. Applying the wrong escaper, or applying one twice. `VariableNode.context` is
   decided once, by the parser, from which segment the placeholder was found in --
   this module never re-derives or second-guesses it. Escaping is applied exactly
   once, to the raw formatted value, at `_render_variable`; nothing downstream of
   that call ever touches the string again with an escaper.
2. Escaping at the wrong moment: the *value*, never the assembled output. `#each`
   renders its body once per item and lets `_render_variable` escape each value as
   it lands in its own node, rather than building a row's text first and escaping
   the concatenation afterwards -- the latter would escape literal template markup
   (the author's own `{{`-free prose around the placeholder) right along with the
   customer's data, which is a different, wrong program.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.templates.ast import EachNode, IfNode, Node, TextNode, VariableNode
from pigrocrm.core.templates.escaping import RenderContext, escape_for
from pigrocrm.core.templates.parser import TYPST_LINE_MARKER_PREFIX, parse_template

__all__ = [
    "TYPST_LINE_MARKER_PREFIX",
    "DeclaredVariable",
    "format_value",
    "render_template",
]

ENTITY = "template"
FIELD = "corpo_markdown"


@dataclass(frozen=True)
class DeclaredVariable:
    """One entry of a template's `variabili_dichiarate`.

    Declared, not deduced (spec 4.3): the compilation form shows label, type and
    whether it is required, and the render fails with a precise error if a required
    one is missing -- instead of producing a PDF with a hole in it.

    `tipo` is one of the nine `FieldType` values in fields/types.py, so the frontend
    can render it with the existing `DynamicFieldRenderer` and nothing new has to
    learn a tenth type.
    """

    nome: str
    etichetta: str
    tipo: str
    obbligatoria: bool


def _is_blank(value: Any) -> bool:
    """Used only to decide whether a *declared* variable's value counts as
    "supplied" (`_check_declared` below) -- not to decide `#if` truthiness, which
    is plain Python truthiness a few lines down in `_render_nodes` and must stay
    that way: `False` and `0` are real answers to a required field (a checkbox the
    user actually unchecked, a discount actually set to zero), so they satisfy a
    required declaration, but they are exactly what an author writing
    `{{#if sconto}}` means by "nothing to show" and must still take the else
    branch. One boolean cannot serve both questions; this function only ever
    answers the first. `test_false_and_zero_satisfy_a_required_variable` pins both
    halves of that distinction at once.

    The container check differs from `fields.validator.is_blank` by one type: this
    also treats an empty *dict* as blank, which that function does not need to,
    since a custom field's coerced value is never a raw dict. `#if` needing `{}` to
    read as "nothing here" (`test_if_treats_every_empty_shape_as_false`) is a
    property of plain truthiness, not of this function, but a required declared
    variable whose value happens to be `{}` should not satisfy the requirement
    either, so the container check is widened here rather than narrowed to match.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def format_value(value: Any) -> str:
    """A value as text, before escaping.

    `Decimal` is formatted with `str`, never `float`: a binary float cannot represent
    1234.56 exactly, and the drift is a bug the moment it reaches an offer. The same
    rule the `Numeric(12, 2)` columns exist for. Checked before the general
    fallback, and before any numeric-type check that does not exist here: `bool` is
    a subtype of `int` in Python, so it must be checked first or `True`/`False`
    would fall through to `str(value)` and print as "True"/"False" instead of the
    Italian a template author actually wrote the document for.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Si" if value else "No"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _resolve(path: tuple[str, ...], scopes: list[dict[str, Any]]) -> tuple[bool, Any]:
    """Walk `path` against the innermost scope that has its first segment.

    Returns `(found, value)` rather than raising, because `#if` and `#each` treat a
    missing path as "nothing here" while a bare variable treats it as an error, and
    only the caller knows which of the two it is. Once a scope is chosen because it
    has `path[0]`, the walk commits to that scope for the rest of `path` -- it does
    not fall further outward if a later segment is missing there, so `{{a.b}}` with
    an inner scope's `a` lacking `b` reports "not found", it does not go looking for
    a *different* `a` in an outer scope.
    """
    for scope in reversed(scopes):
        if path[0] not in scope:
            continue
        current: Any = scope[path[0]]
        for part in path[1:]:
            if not isinstance(current, dict) or part not in current:
                return False, None
            current = current[part]
        return True, current
    return False, None


def _check_declared(declared: tuple[DeclaredVariable, ...], values: dict[str, Any]) -> None:
    for variable in declared:
        if variable.obbligatoria and _is_blank(values.get(variable.nome)):
            raise ValidationFailed(
                ENTITY,
                variable.nome,
                f"variabile obbligatoria mancante: {variable.etichetta}",
                expected="un valore non vuoto",
            )


def render_template(
    source: str,
    values: dict[str, Any],
    declared: tuple[DeclaredVariable, ...] = (),
) -> str:
    """Compile `source` with `values`. Raises `ValidationFailed` naming the template
    line for anything the template needs that `values` does not actually supply --
    a required declared variable, an unresolved `{{path}}`, an `#each` pointed at
    something that is not a list -- rather than rendering a PDF with a hole in it.
    """
    _check_declared(declared, values)
    nodes = parse_template(source)
    # An optional declared variable defaults to `None`, so `{{note}}` for a note
    # nobody filled in renders as empty text rather than as an unresolved-variable
    # error -- the error is reserved for a path the template needs that no
    # supplied *or* declared-optional value covers. `values` is layered on top and
    # always wins, so an actual (even falsy) value is never masked by this default.
    #
    # Fix round 1, item 3: this used to seed `""` unconditionally, regardless of
    # `tipo`. For a scalar type that is merely cosmetic -- `format_value("")` and
    # `format_value(None)` are both `""`, and `bool("")`/`bool(None)` are both
    # falsy, so `{{note}}` and `{{#if note}}` behave identically either way -- but
    # for `multiselect` it was a real bug: `{{#each righe}}` resolved `righe` to
    # the string `""`, which is not a list, and raised "'righe' non e' una lista"
    # -- on the exact template that renders as nothing at all if `righe` is never
    # declared. Declaring an optional variable must never make a template *more*
    # likely to fail than leaving it undeclared.
    #
    # `None` is the fix, for every type, not a per-type table of empty values
    # (`[]` for multiselect, `False` for checkbox, ...): a hardcoded table is
    # exactly one more list this project has already paid once for trusting to
    # stay complete (see escaping.py's own docstring) -- and it is unnecessary
    # here, because every consumer of a resolved value already interprets `None`
    # correctly for whatever shape it is actually used as. `_render_each` already
    # treats `value is None` as "no rows" (the same branch a genuinely absent
    # path takes); plain Python truthiness already treats `None` as falsy for
    # `#if`, the same as `False`, `0` or `[]`; and `format_value(None)` is `""`
    # for a bare substitution. `tipo` therefore still is not consulted here --
    # matching it correctly does not require branching on it.
    optional_defaults: dict[str, Any] = {v.nome: None for v in declared if not v.obbligatoria}
    scopes: list[dict[str, Any]] = [{**optional_defaults, **values}]
    out: list[str] = []
    _render_nodes(nodes, scopes, out)
    return "".join(out)


def _render_nodes(nodes: tuple[Node, ...], scopes: list[dict[str, Any]], out: list[str]) -> None:
    for node in nodes:
        match node:
            case TextNode(text=text):
                # Never escaped, and never touched here beyond appending it: it is
                # the template author's own markup, already carrying the parser's
                # `// pigrocrm:line=` marker wherever one applies (see parser.py).
                out.append(text)
            case VariableNode(path=path, context=context, line=line):
                out.append(_render_variable(path, context, line, scopes))
            case IfNode(path=path, then=then, otherwise=otherwise):
                found, value = _resolve(path, scopes)
                # Plain Python truthiness, not `_is_blank`: `False` and `0` must
                # take the else branch here even though `_is_blank` (correctly, for
                # its own job) does not consider either one blank -- see
                # `_is_blank`'s own docstring. A missing path (`found` is `False`)
                # also takes the else branch, never an error: a conditional's whole
                # job is to ask whether something is there.
                _render_nodes(then if found and value else otherwise, scopes, out)
            case EachNode(path=path, line=line, body=body):
                _render_each(path, line, body, scopes, out)


def _render_variable(
    path: tuple[str, ...], context: RenderContext, line: int, scopes: list[dict[str, Any]]
) -> str:
    found, value = _resolve(path, scopes)
    if not found:
        raise ValidationFailed(
            ENTITY,
            FIELD,
            f"riga {line}: variabile '{'.'.join(path)}' non risolta",
            expected="una variabile dichiarata dal template",
        )
    # `context` came from the node the parser built for this exact placeholder --
    # never re-derived from the path, the value, or anything else this function
    # could get wrong. Escaping the *value* here, once, before it is ever
    # concatenated with any surrounding text, is what keeps a `#each` body's
    # repeated rendering from double-escaping or escaping the author's own markup.
    try:
        return escape_for(context, format_value(value))
    except ValueError as exc:
        raise ValidationFailed(
            ENTITY, FIELD, f"riga {line}: {exc}", expected="testo senza caratteri di controllo"
        ) from exc


def _render_each(
    path: tuple[str, ...],
    line: int,
    body: tuple[Node, ...],
    scopes: list[dict[str, Any]],
    out: list[str],
) -> None:
    found, value = _resolve(path, scopes)
    if not found or value is None:
        # Missing entirely, or explicitly null: both read as "no rows yet", a
        # common shape for an optional relation that has not been filled in, and
        # render as nothing rather than an error.
        return
    if not isinstance(value, (list, tuple)):
        # Anything else -- a string, a number, a dict -- is not "no rows", it is
        # the wrong shape entirely, and worth surfacing rather than silently
        # iterating zero (or, for a string, character-by-character) times.
        raise ValidationFailed(
            ENTITY,
            FIELD,
            f"riga {line}: '{'.'.join(path)}' non e' una lista",
            expected="una lista di elementi",
        )
    for item in value:
        # `this` is the item itself; a dict item's own keys also become a scope, so
        # `{{nome}}` inside `{{#each righe}}` reads the row's `nome` and falls back
        # to the outer scope when the row has none (`_resolve` walks scopes
        # outward). Pushed and popped per item, not left on the stack, so a
        # `{{this}}` two loops removed cannot see an inner loop's own item.
        frame: dict[str, Any] = {"this": item}
        if isinstance(item, dict):
            frame.update(item)
        scopes.append(frame)
        try:
            _render_nodes(body, scopes, out)
        finally:
            scopes.pop()
