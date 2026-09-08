"""The parsed shape of a template.

Every node is frozen and carries the template line it came from. The line is what
turns "qualcosa e' andato storto" into "riga 42 del template": both the parser's own
syntax errors and, later, Typst's compile errors are reported against it.
"""

from dataclasses import dataclass

from pigrocrm.core.templates.escaping import RenderContext


@dataclass(frozen=True)
class TextNode:
    """Literal template text. Never escaped -- it is the author's own markup."""

    text: str


@dataclass(frozen=True)
class VariableNode:
    """A `{{path.to.value}}`.

    `context` is decided by the segment this placeholder was found in, not by
    guessing at render time. It is the whole point of parsing rather than replacing.
    """

    path: tuple[str, ...]
    context: RenderContext
    line: int


@dataclass(frozen=True)
class IfNode:
    path: tuple[str, ...]
    line: int
    then: tuple["Node", ...]
    otherwise: tuple["Node", ...]


@dataclass(frozen=True)
class EachNode:
    path: tuple[str, ...]
    line: int
    body: tuple["Node", ...]


Node = TextNode | VariableNode | IfNode | EachNode
