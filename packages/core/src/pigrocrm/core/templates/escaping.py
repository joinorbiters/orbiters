"""Escaping a value for the context it lands in, never once for the whole document.

The render is two-staged: a Markdown template becomes compiled Markdown, Pandoc turns
that into Typst, Typst composes the PDF. A value in an ordinary paragraph is escaped
for Markdown and Pandoc handles the Typst layer for it; a value inside a raw
`{=typst}` block is passed through by Pandoc untouched, so nothing but this module
stands between it and the compiler. the previous system applied one uniform `escapeTypstText` to
everything (`website/vite.config.js:71-77`) and patched the character list each time a
new symbol broke a document -- the commit `fix(pdf): escape @ and other
typst-sensitive chars in placeholders` is that pattern in its final form. The fix is
not a longer list; it is knowing which list applies.
"""

import re
from typing import Literal
from urllib.parse import quote

RenderContext = Literal["markdown", "typst", "url"]

# Pandoc's Markdown accepts a backslash escape before any ASCII punctuation mark, so
# every character here becomes literal text rather than syntax.
#
# `&` is not in the spec's §3.3 list and is added deliberately: Pandoc reads `&amp;`
# as a character entity, so a customer whose name really contains the six characters
# `&amp;` would otherwise see a bare `&` in the PDF -- data quietly altered, which is
# the same class of defect as stripping a NUL byte.
#
# `#` is absent from this tuple on purpose: it is only syntax at the start of a line
# (an ATX heading) and is handled separately below, because escaping every `#` would
# turn "C#" into "C\#" in the output of engines less forgiving than Pandoc.
_MARKDOWN_SPECIALS: tuple[str, ...] = ("\\", "`", "*", "_", "[", "]", "<", ">", "&")

# Typst treats `\` followed by any non-alphanumeric character as that character
# literally, so the same one-backslash rule applies here.
#
# The spec's §3.3 list is `\ # $ @ " < >`. Four characters are added:
#   `[` `]` -- a raw {=typst} block in this project's own carried-over template writes
#             each table cell as `[...]` (see render/assets/template-offer.md, the
#             `#table(...)` block); an unbalanced bracket in a value closes the cell
#             early and the compile fails.
#   `*` `_` -- Typst's own strong/emphasis markers. Unescaped, a value containing them
#             renders bold inside a raw block, which is the Markdown bug one layer down.
# The backtick is added for the same reason as `*`: it opens a raw block in Typst markup.
_TYPST_SPECIALS: tuple[str, ...] = (
    "\\",
    "#",
    "$",
    "@",
    '"',
    "<",
    ">",
    "[",
    "]",
    "*",
    "_",
    "`",
)

# `re.fullmatch` is used everywhere in this project rather than `re.match` with `$`,
# because `$` matches before a trailing newline. Here the pattern is used with `sub`,
# where that distinction does not arise -- but the anchor is written `\Z`-free and
# line-anchored explicitly so nobody has to reason about it.
_LINE_LEADING_HASH = re.compile(r"^([ \t]*)#", re.MULTILINE)
_ANY_NEWLINE = re.compile(r"\r\n|\r|\n")


def _reject_nul(value: str) -> str:
    """Rejects, never strips -- the same decision `pigrocrm.core.validation.SafeStr`
    makes, for the same reason. A NUL byte here would also survive into a file this
    module writes and be handed to a subprocess."""
    if "\x00" in value:
        raise ValueError("il testo contiene un carattere nullo (\\x00), non ammesso")
    return value


def _escape_each(value: str, specials: tuple[str, ...]) -> str:
    """One pass over the *original* characters.

    Escaping character by character in a single loop is what makes the backslash
    rule work: each input `\\` becomes `\\\\`, and the backslashes this function
    itself emits are never re-examined. A chain of `str.replace` calls cannot do
    that -- whichever replacement runs second sees the first one's output -- which
    is why the previous system's chain had to put `\\` first and could still be broken by adding a
    new rule above it.
    """
    marked = set(specials)
    return "".join("\\" + ch if ch in marked else ch for ch in value)


def escape_markdown(value: str) -> str:
    """For a placeholder that lands in ordinary Markdown body text."""
    escaped = _escape_each(_reject_nul(value), _MARKDOWN_SPECIALS)
    return _LINE_LEADING_HASH.sub(r"\1\\#", escaped)


def escape_typst(value: str) -> str:
    """For a placeholder that lands inside a raw ```{=typst} block or span.

    Newlines collapse to a single space: the value is landing inside a syntactic
    unit -- a table cell, a header field -- and a raw newline there changes the
    layout of a document nobody is going to proof-read before it is sent.
    """
    flattened = _ANY_NEWLINE.sub(" ", _reject_nul(value))
    return _escape_each(flattened, _TYPST_SPECIALS)


def escape_url(value: str) -> str:
    """For a placeholder that lands in a link or image destination.

    `safe=""` on purpose: a destination is a single opaque component here, so even
    `/` and `:` are encoded. A placeholder is never the whole URL in this project's
    templates -- it is always a path segment or a query value.
    """
    return quote(_reject_nul(value), safe="")


def escape_for(context: RenderContext, value: str) -> str:
    match context:
        case "markdown":
            return escape_markdown(value)
        case "typst":
            return escape_typst(value)
        case "url":
            return escape_url(value)
    raise ValueError(f"contesto di escaping sconosciuto: {context!r}")
