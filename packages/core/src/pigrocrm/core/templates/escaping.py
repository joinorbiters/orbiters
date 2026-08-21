r"""Escaping a value for the context it lands in, never once for the whole document.

The render is two-staged: a Markdown template becomes compiled Markdown, Pandoc turns
that into Typst, Typst composes the PDF. A value in an ordinary paragraph is escaped
for Markdown and Pandoc handles the Typst layer for it; a value inside a raw
`{=typst}` block is passed through by Pandoc untouched, so nothing but this module
stands between it and the compiler. Acme applied one uniform `escapeTypstText` to
everything (`website/vite.config.js:71-77`) and patched the character list each time a
new symbol broke a document -- the commit `fix(pdf): escape @ and other
typst-sensitive chars in placeholders` is that pattern in its final form.

The fix is not a longer list, and -- found in review, against real compiles, not
just the two strings this module's own first version was tested with -- it is not two
shorter, hand-picked lists either. That first version gave `escape_typst` an `@` and
did not give `escape_markdown` one; gave neither a `/`, and a bare `//` opens a Typst
line comment, so a customer named `Rossi // nota` deleted the rest of that line from a
real, cleanly-compiled PDF with no error at all. Two independently curated lists drift
apart from each other for the same reason one list drifts from correct over time:
nothing forces either to be complete, or to agree with the other. The fix is to stop
enumerating which characters are dangerous and escape the entire ASCII punctuation
class, unconditionally, in both contexts: both Pandoc's Markdown and Typst's markup
accept a backslash before any of the 32 characters in `string.punctuation` as that
character literally, in any position, so there is no character left for a list to
omit -- confirmed by compiling real PDFs with all 32 present at once, see
`test_every_ascii_punctuation_character_survives_markdown_context` and its `typst`
sibling below.

Known, accepted limitation, not closed by this module: a value that lands in ordinary
Markdown body text and happens to contain a literal `--`, `---`, or `...` still
reaches the compiled PDF retypeset as an en dash, an em dash, or an ellipsis. Escaping
does not prevent this, because it cannot reach far enough: `escape_markdown`'s output
is Markdown *source*, and Pandoc's own Typst *writer* re-serialises that source's
parsed content afterwards, on its own rules, before Typst ever sees it. Pandoc's
writer does defend a lone character that is individually dangerous to Typst (`$`, `~`,
a backtick) by re-escaping it on the way out, but a lone `-` or `.` is not individually
dangerous, so it writes each one out bare -- and Typst's *own* lexer, independent of
Pandoc, merges two or three adjacent bare ones into a dash or an ellipsis no matter
which template put them there. `escape_typst` does not have this problem: its output
is never re-serialised by anything, so an escaped `--` (`\-\-`) reaches Typst already
protected and survives.
"""

import re
import string
from typing import Literal
from urllib.parse import quote, urlsplit

RenderContext = Literal["markdown", "typst", "typst_string", "url", "verbatim", "xml"]

# Every ASCII punctuation character, escaped unconditionally, in both contexts -- see
# the module docstring for why a curated subset per context is exactly the defect this
# replaces. Escaping `#` unconditionally rather than only at the start of a line (the
# first version's rule, since a bare `#` mid-sentence is already literal to Pandoc) is
# simpler and no less correct: a backslash-escaped `#` mid-sentence round-trips through
# Pandoc to the identical bare `#` an unescaped one would have produced.
_ASCII_PUNCTUATION: frozenset[str] = frozenset(string.punctuation)

# Typst's own lexer treats as a line terminator: a lone `\r` or `\n`, the two-character
# `\r\n`, and five characters Pandoc's Markdown reader never treats as line-structuring
# whitespace at all -- U+000B (vertical tab), U+000C (form feed), U+0085 (next line),
# U+2028 (line separator) and U+2029 (paragraph separator).
#
# An ordinary `\n`, or a real blank-line paragraph break, is already safe without this:
# Pandoc's own AST records where a block began, so its Typst writer defends whatever
# character starts the next one (confirmed live: a literal `=` placed right after a
# genuine paragraph break comes out of Pandoc as `\=`, not a bare `=`). The five exotic
# characters get no such defence, because Pandoc's reader does not recognise any of
# them as a boundary in the first place -- each passes through a value as ordinary,
# harmless-looking text and reaches the compiled Typst source as a literal code point,
# where Typst's lexer, unlike Pandoc's reader, does treat it as a real line break
# (confirmed live: "Rossi" + U+2028 + "= TITOLO" compiles to a genuine level-1 heading,
# in both contexts this module serves). Collapsing every one of them to a plain space
# removes the line a value could otherwise manufacture, rather than relying on
# whichever compiler's own escaping happens to defend that particular position.
_NEWLINE_EQUIVALENTS = re.compile(
    "\r\n|[\r\n\v\f"  # CRLF as one unit; lone CR/LF; vertical tab; form feed
    + chr(0x85)  # NEL, next line
    + chr(0x2028)  # LS, line separator
    + chr(0x2029)  # PS, paragraph separator
    + "]"
)


def _reject_nul(value: str) -> str:
    """Rejects, never strips -- the same decision `pigrocrm.core.validation.SafeStr`
    makes, for the same reason. A NUL byte here would also survive into a file this
    module writes and be handed to a subprocess."""
    if "\x00" in value:
        raise ValueError("il testo contiene un carattere nullo (\\x00), non ammesso")
    return value


def _escape_each(value: str, specials: frozenset[str]) -> str:
    """One pass over the *original* characters.

    Escaping character by character in a single loop is what makes the backslash
    rule work: each input `\\` becomes `\\\\`, and the backslashes this function
    itself emits are never re-examined. A chain of `str.replace` calls cannot do
    that -- whichever replacement runs second sees the first one's output -- which
    is why Acme's chain had to put `\\` first and could still be broken by adding a
    new rule above it.
    """
    return "".join("\\" + ch if ch in specials else ch for ch in value)


def escape_markdown(value: str) -> str:
    """For a placeholder that lands in ordinary Markdown body text.

    Escapes every ASCII punctuation character, unconditionally -- see
    `_ASCII_PUNCTUATION`. Collapses every Typst-recognised line terminator to a
    single space -- see `_NEWLINE_EQUIVALENTS` -- even though this value's
    *immediate* target is Pandoc, not Typst: it still ends its life as Typst source
    one stage later, once Pandoc's own writer re-serialises it, and Pandoc's own
    notion of where a line boundary is is not Typst's.
    """
    flattened = _NEWLINE_EQUIVALENTS.sub(" ", _reject_nul(value))
    return _escape_each(flattened, _ASCII_PUNCTUATION)


def escape_typst(value: str) -> str:
    """For a placeholder that lands inside a raw ```{=typst} block, in *markup*
    position -- as ordinary text, or as the content of a `[...]` block.

    This is not correct for *string-literal* position -- inside `#text("...")`,
    `#link("...")` and similar, which are common inside a raw typst block. A Typst
    string literal has its own, much smaller escape grammar (`\\`, `\"`, and a
    handful of named/unicode escapes); a backslash before any other character is not
    a recognised escape there, and Typst keeps the backslash as a visible, literal
    character instead of consuming it (confirmed live: `#text("C\\# dev")` renders as
    the four characters `C\\# dev`, backslash included). Fix round 1, item 2: a
    reviewer found this live and unguarded -- `#link("{{u}}")` is an obvious thing
    for a template author to write, and this escaper turns a working URL into a
    dead one (`#link("https\\:\\/\\/esempio\\.it")`, confirmed live by reading the
    compiled PDF's own `/URI` annotation). `escape_typst_string` below is the
    narrower escaper for that position; `pigrocrm.core.templates.parser` decides,
    at parse time, which of the two a given placeholder needs.

    Newlines -- and everything else Typst's own lexer treats as one, see
    `_NEWLINE_EQUIVALENTS` -- collapse to a single space: the value is landing inside
    a syntactic unit -- a table cell, a header field -- and a raw line break there
    changes the layout of a document nobody is going to proof-read before it is sent.
    """
    flattened = _NEWLINE_EQUIVALENTS.sub(" ", _reject_nul(value))
    return _escape_each(flattened, _ASCII_PUNCTUATION)


# Only these two characters are a recognised escape inside a Typst string literal
# (plus a handful of named/unicode escapes -- `\n`, `\u{...}` and similar -- this
# module has no reason to produce, since it only ever escapes *literal* characters
# a customer's own value happens to contain, never emits a named escape itself).
_TYPST_STRING_SPECIALS: frozenset[str] = frozenset({"\\", '"'})


def escape_typst_string(value: str) -> str:
    r"""For a placeholder that lands inside a Typst *string literal* -- the
    argument of `#link("...")`, `#text("...")` and similar, as opposed to markup
    position (`escape_typst`, above).

    Escaping the full ASCII punctuation class here -- `escape_typst`'s own rule --
    is wrong in this position for the same reason that function's docstring
    describes: a backslash before, say, `&` is not a recognised escape inside a
    string literal, so Typst keeps it as a visible, literal backslash instead of
    consuming it (confirmed live: `#text("Rossi \& C\.")` renders the backslashes).
    Only `\` and `"` need doubling here; escaping anything else would be visible,
    not merely redundant.

    Escaping `"` is what stops a hostile value from closing the string early and
    handing the rest of itself to Typst as real code -- confirmed live with a value
    built to do exactly that (`x") #import("/etc/passwd") #text("`), which stays
    inert literal text end to end once escaped this way, never a second argument,
    never a second function call.

    Newlines still collapse to a single space, for the same reason `escape_typst`
    collapses them: the value is landing inside one syntactic unit, not a place a
    raw line break belongs.
    """
    flattened = _NEWLINE_EQUIVALENTS.sub(" ", _reject_nul(value))
    return _escape_each(flattened, _TYPST_STRING_SPECIALS)


def _is_trustworthy_absolute_url(value: str) -> bool:
    """True for a value this module will write out as a literal link, rather than
    treat as opaque data.

    Deliberately narrow: `http`/`https` scheme, a non-empty host, and no whitespace
    or control character anywhere in the value. A customer's own `sito_web` field is
    the case this exists for; a scheme this module has never seen (`javascript:`,
    `data:`, a bare `esempio.it` with no scheme at all) or a value carrying a
    character that has no business in a URL falls through to the opaque path below
    instead, on purpose -- this function decides *whether* to trust the value as a
    URL at all, not how to neutralise one that has already been trusted.
    """
    if any(ch.isspace() or ord(ch) < 0x20 for ch in value):
        return False
    parsed = urlsplit(value)
    return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)


def escape_url(value: str) -> str:
    r"""For a placeholder that lands in a link or image destination.

    A customer's own URL -- `cliente.sito_web`, the case the spec names -- is meant
    to end up as a *working* link, not as inert text: the whole point of putting it
    in `[il sito]({{cliente.sito_web}})` is that "il sito" is clickable. This
    function used to `quote(value, safe="")` unconditionally, which percent-encodes
    `:` and `/` right along with everything else -- `https://esempio.it/a?b=c` came
    out as `https%3A%2F%2Fesempio.it%2Fa%3Fb%3Dc`, a string Pandoc writes out
    byte-for-byte as the link target, so the PDF's own link annotation pointed at
    that literal, broken, relative-looking path instead of the customer's site
    (confirmed live by reading the annotation back out of a compiled PDF, not by
    asserting a string -- see test_template_escaping.py's real-compile tests below).

    So a value trusted as an absolute `http`/`https` URL (`_is_trustworthy_absolute_
    url` above) is written in Pandoc's *angle-bracket* destination form, `<...>`,
    instead: the one destination spelling in this grammar where `:`, `/`, `?`, `=`
    and `&` stay literal, because the closing delimiter is `>`, not "the next
    unescaped `)`, space, or end of line" the way the bare form's is. Only `\`, `<`
    and `>` need escaping inside it -- `_is_trustworthy_absolute_url` already
    refused to trust a value containing whitespace or a control character, so a
    space or a newline never reaches this branch to begin with, and there is nothing
    else left to neutralise. A hostile value cannot use this path to break out of
    the destination: a raw `)`, a `](`, or any other bare-form-only special
    character is just literal text between `<` and `>` -- confirmed live for a value
    containing all four at once (test_url_context_survives_a_hostile_value_without_
    breaking_the_document_for_real).

    A value this function will not vouch for -- no scheme, a scheme that is not
    `http`/`https`, or anything containing whitespace or a control character -- is
    still `quote(value, safe="")`'d exactly as before: an opaque, inert destination
    that cannot break out of the surrounding `(...)` either, just one that does not
    go anywhere in particular. Explicit, not a bug: this module will render a
    customer's real website link, but it will not turn arbitrary customer text into
    a clickable destination on the strength of it merely being unescaped-safe to do
    so, and it will not follow a `javascript:`/`data:`/`file:` scheme just because
    nothing here would technically break.
    """
    value = _reject_nul(value)
    if _is_trustworthy_absolute_url(value):
        return "<" + _escape_each(value, frozenset({"\\", "<", ">"})) + ">"
    return quote(value, safe="")


# XML 1.0 Char production (spec section 2.2): #x9 | #xA | #xD | [#x20-#xD7FF] |
# [#xE000-#xFFFD] | [#x10000-#x10FFFF]. Everything else -- the C0 controls other than
# tab/LF/CR, the surrogate range (reachable in a Python str, e.g. from a lone
# "\ud800"), and the two non-characters #xFFFE/#xFFFF -- has no representation at
# all: not as a literal byte, and not as a numeric character reference either, so no
# escaper could rescue it. A serialiser that emits one produces a file no conformant
# parser will open, which on a fiscal document means an outright rejection with no
# diagnostic worth reading. Written with explicit \\x/\\u/\\U escapes, not the literal
# code points themselves, since some of those code points do not survive every text
# encoding or editor round-trip intact.
_INVALID_XML_CHARS = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def escape_xml(value: str) -> str:
    """For a value that lands as the text of an XML element.

    Returns `value` **unchanged**. That is the whole rule, and it is deliberate: this
    slice builds the FatturaPA document as an `lxml` element tree and serialises it
    once, so the serialiser is the single escaping pass and anything this function
    substituted would be escaped a second time on the way out -- `&` would reach the
    Agenzia delle Entrate as `&amp;amp;`. Acme's own literal-backslash defect
    (`normalizeSingleLine` ran `escapeTypstText` and then `escapeXml` over the same
    string) is that mistake in its other direction. The `xml` context therefore exists
    to say, explicitly and in the same module as the other four contexts, that the
    correct number of escaping passes for an XML target is one and it does not happen
    here.

    What it does do is refuse what no escaper can fix: a code point outside XML 1.0's
    `Char` production. `SafeStr` already stops a NUL byte at the schema boundary; this
    closes the rest of the class rather than that one case.
    """
    invalid = _INVALID_XML_CHARS.search(value)
    if invalid is not None:
        raise ValueError(
            "il testo contiene un carattere non rappresentabile in XML 1.0: "
            f"U+{ord(invalid.group(0)):04X}"
        )
    return value


def escape_for(context: RenderContext, value: str) -> str:
    match context:
        case "markdown":
            return escape_markdown(value)
        case "typst":
            return escape_typst(value)
        case "typst_string":
            return escape_typst_string(value)
        case "url":
            return escape_url(value)
        case "xml":
            return escape_xml(value)
        case "verbatim":
            # No escaper exists for this context on purpose, not by omission: a
            # verbatim region (a plain code span or fenced code block, as opposed to
            # a raw {=typst} one) is not markdown-escape-processed by Pandoc at all,
            # so a backslash this module might add would show up as a literal
            # backslash in the rendered document instead of being consumed as an
            # escape (fix round 1, items 2-3). The parser never tokenises inside a
            # verbatim segment for exactly this reason -- see
            # pigrocrm.core.templates.parser, where a verbatim Segment's whole text
            # becomes one opaque TextNode and no VariableNode is ever created with
            # this context. Reaching this branch at all means that invariant broke.
            raise ValueError(
                "verbatim non ha una regola di escaping: un placeholder in un "
                "segmento verbatim non viene mai sostituito, quindi non dovrebbe "
                "mai raggiungere escape_for"
            )
    raise ValueError(f"contesto di escaping sconosciuto: {context!r}")
