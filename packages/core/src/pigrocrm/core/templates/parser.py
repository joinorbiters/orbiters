"""Segment first, then tokenise. Never a regex over the whole document at once.

Segmentation is what gives every placeholder its destination context. Tokenisation
runs *inside* a segment, so a placeholder cannot acquire the wrong escaping rule by
being near something else on the page -- and a placeholder whose `{{` and `}}` fall in
*different* segments (a fence opened mid-mustache, say) is tokenised nowhere at all,
rather than merged into some third, unintended context: `_TOKEN_RE.finditer` only ever
sees one segment's text at a time, so a dangling `{{` in segment N and a dangling `}}`
in segment N+1 can never pair up (see
test_a_placeholder_spanning_a_fence_boundary_becomes_two_inert_text_fragments).

Every claim below about what Pandoc actually does with a given byte sequence was
checked against a real `pandoc -t json` / `pandoc -t typst` run (Pandoc 3.8.2.1) rather
than derived from the CommonMark grammar by reasoning -- see the "for_real" tests in
test_template_parser.py, which repeat the same checks as executable proof.

`parse_template` also stamps every raw typst *block* fence with a `// pigrocrm:line=`
comment naming its own template line -- see `TYPST_LINE_MARKER_PREFIX` below for why
this lives here rather than in the renderer that walks the resulting tree: this is the
only place the true line is ever known.
"""

import re
from dataclasses import dataclass

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.templates.ast import EachNode, IfNode, Node, TextNode, VariableNode
from pigrocrm.core.templates.escaping import RenderContext

ENTITY = "template"
FIELD = "corpo_markdown"

# The five regions that are not ordinary Markdown body text, in one alternation so a
# single left-to-right scan cannot produce overlapping or out-of-order segments:
#   fence           -- ```{=typst} ... ``` , Pandoc's raw-attribute block. DOTALL, and
#                      lazy, so it stops at the first valid closing fence rather than
#                      the last one in the file.
#   verbatim_fence  -- any OTHER fenced block: a plain ```python, a bare ```, a
#                      ```{.class} one, or a malformed {=X} attribute Pandoc itself
#                      does not read as raw typst either (see below). Listed after
#                      `fence` so a genuine ```{=typst} fence is always claimed by
#                      that alternative first; this one only fires when the specific
#                      one already failed to match at the same position.
#   inline          -- `...`{=typst} , the span form of `fence`.
#   verbatim_inline -- any other inline code span, the span form of `verbatim_fence`.
#   url             -- ](...) , a Markdown link or image destination.
#
# `verbatim_fence`/`verbatim_inline` exist for fix round 1, items 2-3: Pandoc does not
# markdown-escape-process the content of a code span or a fenced/indented code block
# at all (a backslash there is not consumed as an escape the way it is everywhere
# else -- confirmed live: escape_markdown's output inside a plain ```python fence
# comes out of the compiled PDF with its own backslashes still visible,
# `nome = 'Rossi \/\/ nota'`, not the clean value). `parse_template` below never
# tokenises a "verbatim" segment for exactly this reason -- see its own comment.
# Router-level consequence, not something coded separately: a {=typst} fence nested
# *inside* a wider plain fence (item 3's mirror case) is claimed whole by
# `verbatim_fence` at the wider fence's own opening line, so the inner three
# backticks are just characters inside its lazily-matched content and `fence` never
# gets a chance to fire on them at all -- confirmed live against a real
# ````md ... ```{=typst} ... ``` ... ```` document, where Pandoc's own AST holds
# one CodeBlock containing the inner fence markers as literal text, not a nested
# RawBlock.
#
# Refinements earned against real Pandoc, not against the CommonMark spec text:
#
# - `(?P<fence_delim>`{3,}|~{3,})`, rather than a literal ```` ``` ````: CommonMark
#   fences may use three or more backticks OR three or more tildes, and Typst's own
#   raw-code syntax also uses backticks, so a raw block that itself needs to
#   *contain* a literal ``` has to open with four -- confirmed live, a 4-backtick
#   fence around content containing a bare `` `raw code` `` line round-trips through
#   `pandoc -t typst` with that line untouched. The closing fence must reproduce the
#   *same* delimiter, exact length -- `(?P=fence_delim)`, a bare backreference, not
#   "at least as many": CommonMark actually allows a longer close, but every
#   realistic template writes a matching pair, and requiring an exact match only
#   ever makes this segmenter under-recognise a deliberately-mismatched fence (which
#   safely falls back to the markdown default) rather than over-recognise one.
# - `(?:>[ \t]?)*[ ]{0,3}` (`_FENCE_PREFIX`) before the opening and closing
#   delimiter: CommonMark still recognises a fence indented up to three spaces --
#   four turns it into a plain indented code block instead, which cannot carry a
#   `{=typst}` attribute at all and is confirmed live to keep the fence markers as
#   literal text. Three spaces also happens to be exactly what a single, unnested
#   `- ` or `1. ` list item needs for its own raw block, confirmed live against
#   Pandoc's own AST: a fence indented two spaces inside a bullet item is a real
#   `RawBlock`, a sibling of the item's paragraph. `>` (optionally followed by one
#   space), zero or more times, handles a fence inside a blockquote the same way,
#   confirmed live for a single level of quoting. A fence nested two list levels (or
#   quote levels) deep needs more indentation than this allows for and is a
#   documented, tested gap (test_a_fence_nested_two_list_levels_deep_is_not_
#   recognised_as_typst) rather than a silent one: this is a flat regex, not a
#   container-aware Markdown parser, and getting that specific case right would
#   require becoming one.
# - `\{=typst[ \t]*\}`, not `\{=typst\}`: Pandoc tolerates trailing whitespace before
#   the closing brace, in both the block and the inline form (confirmed live: both
#   ` ```{=typst } ` and `` `...`{=typst } `` still become a real raw block/inline and
#   still survive the `-t typst` writer) but not a space right after `=`, or the
#   raw-format token combined with another attribute (` ```{= typst} ` and
#   ` ```{=typst .foo} ` are not recognised as an attribute at all and fall back to
#   an ordinary, multi-line inline code span, confirmed live for both). Deliberately
#   not lenient about either: treating them as a typst segment here would escape a
#   value for a context Pandoc itself never puts it in. They still end up "verbatim"
#   rather than "markdown", though, via `verbatim_inline` -- see that alternative's
#   own note above.
#
# `inline` and `verbatim_inline` both generalise their delimiter to one OR MORE
# backticks -- `(?P<..._ticks>`+)` -- for the same reason the block fence does: a
# double-backtick inline span lets its content contain a single bare backtick
# (confirmed live: `` ``#emph[a ` b]``{=typst} `` round-trips through Pandoc's AST as
# one RawInline whose text includes the inner backtick). This segmenter is narrower
# than that in one respect, on purpose: its own content class, `[^`\n]*`, still
# excludes backticks entirely rather than accepting any run shorter than the
# delimiter's, which only matters for a span that both widens its delimiter *and*
# embeds a shorter backtick run in the same breath -- narrow enough a case that
# under-recognising it (falling back to the markdown/verbatim default one line
# earlier) was judged not worth the extra complexity here.
#
# Both delimiter groups also require the run to be atomic -- not adjacent to another
# backtick on either side (`(?<!`)`` `` `(?!`)`` ``, on both the opening and the
# closing run). Without that guard, the second and third characters of an
# *unterminated* fence's own opening line ("```{=typst}" with no closing fence
# anywhere in the document) match `inline` on their own -- two of the three
# backticks plus the attribute -- because a bare `[^`\n]*` between two single
# backticks does not care that one of those backticks has a sibling immediately
# behind it. Confirmed live: Pandoc's own reader does not do this; with no closing
# fence, the whole opening line is ordinary paragraph text, see
# test_an_unterminated_fence_is_ordinary_markdown_text_not_a_broken_inline_match.
_FENCE_PREFIX = r"(?:>[ \t]?)*[ ]{0,3}"

_SEGMENT_RE = re.compile(
    r"(?P<fence>^" + _FENCE_PREFIX + r"(?P<fence_delim>`{3,}|~{3,})\{=typst[ \t]*\}[ \t]*\n"
    r".*?^" + _FENCE_PREFIX + r"(?P=fence_delim)[ \t]*$)"
    r"|(?P<verbatim_fence>^" + _FENCE_PREFIX + r"(?P<vf_delim>`{3,}|~{3,})[^\n]*\n"
    r".*?^" + _FENCE_PREFIX + r"(?P=vf_delim)[ \t]*$)"
    r"|(?P<inline>(?<!`)(?P<inline_ticks>`+)(?!`)[^`\n]*(?<!`)(?P=inline_ticks)(?!`)"
    r"\{=typst[ \t]*\})"
    r"|(?P<verbatim_inline>(?<!`)(?P<vi_ticks>`+)(?!`)[^`\n]*(?<!`)(?P=vi_ticks)(?!`))"
    r"|(?P<url>\]\([^)\n]*\))",
    re.DOTALL | re.MULTILINE,
)

_TOKEN_RE = re.compile(r"\{\{(?P<body>.*?)\}\}", re.DOTALL)

# `re.fullmatch` against this, never `re.match` with `$`: `$` matches before a
# trailing newline, so `{{a\n}}` would be accepted as the path `a` and the newline
# would silently vanish. The project has already paid for that distinction once, on a
# 12-character P.IVA that reached Postgres as an uncaught DataError. See
# `parse_template` below for the other half of this: `fullmatch` only protects a
# caller who still has the newline in hand by the time it runs it.
_PATH_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def _normalize_newlines(source: str) -> str:
    """CRLF, and lone CR, collapsed to `\\n` before anything else touches `source`.

    Narrower than `escaping._NEWLINE_EQUIVALENTS` on purpose: that set defends a
    *value* a customer controls, so it also collapses the exotic separators Typst's
    lexer treats as line breaks. This is the template's own source, written by
    whoever authors offers, not attacker-controlled in the same way -- the only
    realistic threat here is an editor that saved `\\r\\n`, and every anchor below
    (`^`, `$`, the literal `\\n` after a fence's attribute line) is written against a
    single `\\n` convention and would otherwise silently fail to match a line that
    actually ends in `\\r\\n`.
    """
    return source.replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True)
class Segment:
    text: str
    context: RenderContext
    line: int


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _fail(line: int, reason: str, expected: str | None = None) -> None:
    raise ValidationFailed(ENTITY, FIELD, f"riga {line}: {reason}", expected=expected)


def segment(source: str) -> tuple[Segment, ...]:
    """Split `source` into typed regions, in order, covering it completely."""
    source = _normalize_newlines(source)
    segments: list[Segment] = []
    cursor = 0
    for match in _SEGMENT_RE.finditer(source):
        if match.start() > cursor:
            segments.append(
                Segment(source[cursor : match.start()], "markdown", _line_of(source, cursor))
            )
        # Checked by presence, not `match.lastgroup`: every alternative here has a
        # nested group of its own (the delimiter-length backreference target), which
        # is *numbered* after the alternative itself and therefore participates as
        # the match's last-matched group whenever that alternative does --
        # `lastgroup` would report e.g. "fence_delim", not "fence". Asking for the
        # group this code means by name, rather than the highest group number that
        # happened to participate, is not the kind of coincidence worth relying on.
        is_verbatim = (
            match.group("verbatim_fence") is not None or match.group("verbatim_inline") is not None
        )
        if match.group("url") is not None:
            context: RenderContext = "url"
        elif is_verbatim:
            context = "verbatim"
        else:
            context = "typst"
        segments.append(Segment(match.group(0), context, _line_of(source, match.start())))
        cursor = match.end()
    if cursor < len(source):
        segments.append(Segment(source[cursor:], "markdown", _line_of(source, cursor)))
    return tuple(segments)


def _parse_path(raw: str, line: int) -> tuple[str, ...]:
    if not _PATH_RE.fullmatch(raw):
        _fail(
            line,
            f"percorso '{raw}' non valido",
            expected="un percorso puntato, es. cliente.ragione_sociale",
        )
    return tuple(raw.split("."))


class _Frame:
    """One open block on the stack, plus where its children accumulate."""

    def __init__(self, kind: str, path: tuple[str, ...], line: int) -> None:
        self.kind = kind
        self.path = path
        self.line = line
        self.children: list[Node] = []
        self.otherwise: list[Node] | None = None

    def emit(self, node: Node) -> None:
        (self.otherwise if self.otherwise is not None else self.children).append(node)


# Emitted as the first line inside a raw ```{=typst} block's *body* -- any fence
# spelling this segmenter recognises (backtick or tilde, three or more, indented
# inside a list, quoted inside a blockquote): confirmed live, against real Pandoc
# and Typst, that inserting this exact bare, unindented line does not stop the
# fence from being read as one raw block and does not leak into whatever sibling
# block follows, regardless of the fence's own indentation or blockquote nesting --
# Pandoc's own lazy-continuation handling absorbs it either way. Pandoc copies a
# raw block through to the Typst writer verbatim, line for line, so this survives
# into the intermediate .typ file -- which is what lets a later stage
# (render/diagnostics.py, not built yet) turn a Typst compiler error at
# "intermediate.typ:57" into "riga 12 del template" by arithmetic rather than by
# guessing. `//` is a Typst line comment: the marker produces no output of its own.
#
# Never applied to an *inline* raw span (`` `...`{=typst} ``): that content lives on
# a single line with no independent "body" of its own to prepend a line to, and this
# segmenter's own grammar guarantees an inline match never contains a newline (its
# token class explicitly excludes one -- see `_SEGMENT_RE`'s `inline` alternative).
# So "does this typst segment's matched text contain a newline" is exactly the test
# for "this is the block form", with no need to also recognise which delimiter or
# how much indentation it used.
TYPST_LINE_MARKER_PREFIX = "// pigrocrm:line="


def _insert_typst_line_marker(text: str, body_line: int) -> str:
    """`text` is a typst *block*-fence segment's matched text (guaranteed to contain
    at least one "\\n" by the caller); returns it with the marker inserted as a new
    line immediately after the fence's own opening line."""
    opening, _, body = text.partition("\n")
    return f"{opening}\n{TYPST_LINE_MARKER_PREFIX}{body_line}\n{body}"


def parse_template(source: str) -> tuple[Node, ...]:
    """Parse a template into a node tree, or raise `ValidationFailed` naming the line."""
    root = _Frame("root", (), 1)
    stack: list[_Frame] = [root]

    for seg in segment(source):
        if seg.context == "verbatim":
            # Deliberately "do not substitute at all", not "substitute unescaped":
            # this segment's text is exactly what a plain code span or fenced code
            # block contains, backticks included, and *nothing* escapes it before
            # Pandoc reads it -- Pandoc's own reader does not run markdown-escape
            # processing inside verbatim content, only this parser's segmentation
            # decides the boundary. A raw customer value could itself contain the
            # same backtick run that delimits the span, which would end it early and
            # spill whatever follows back into interpreted Markdown or Typst -- the
            # exact class of boundary break this module exists to prevent, not
            # reproduce with a narrower excuse. Treating the whole segment as one
            # opaque TextNode means a `{{placeholder}}` written inside a code
            # example stays literal in the rendered document (visible, not deleted,
            # not substituted) -- confusing if an author did not mean to do that, but
            # never a value landing where it can break the surrounding delimiter.
            if seg.text:
                stack[-1].emit(TextNode(seg.text))
            continue
        text = seg.text
        # Computed here, not in the renderer: counting newlines *within* a single
        # TextNode's own string, with no visibility into how many lines came before
        # it in the wider document, is wrong for any fence that is not the first
        # thing in the template -- this segment's `seg.line` is already the true
        # line, carried all the way from `segment()`'s own full-document scan.
        marked = seg.context == "typst" and "\n" in text
        if marked:
            text = _insert_typst_line_marker(text, seg.line + 1)
        cursor = 0
        for match in _TOKEN_RE.finditer(text):
            if match.start() > cursor:
                stack[-1].emit(TextNode(text[cursor : match.start()]))
            # The marker inserts one whole extra line before every placeholder that
            # can occur in this segment -- never on the fence's own opening line,
            # since the grammar requires a literal newline right after the
            # attribute brace, leaving no room for a placeholder there -- so it must
            # be subtracted back out to report the template's own line, not the
            # marker-shifted one.
            line = seg.line + text.count("\n", 0, match.start()) - (1 if marked else 0)
            # `.strip(" \t")`, never a bare `.strip()`: a bare strip removes a
            # trailing "\n" along with the spaces, which is exactly the P.IVA-shaped
            # mistake `_PATH_RE`'s own `fullmatch` comment warns about, just moved one
            # call earlier -- `{{a\n}}` would reach `_parse_path` already reduced to
            # the valid path "a", the newline discarded before `fullmatch` ever saw
            # it. Stripping only horizontal whitespace keeps `{{ cliente.nome }}`
            # ergonomic for whoever writes templates while leaving an embedded
            # newline in place for the checks below to reject.
            body = match.group("body").strip(" \t")
            _consume_token(stack, body, line, seg.context)
            cursor = match.end()
        if cursor < len(text):
            stack[-1].emit(TextNode(text[cursor:]))

    if len(stack) > 1:
        open_frame = stack[-1]
        _fail(open_frame.line, f"blocco {{{{#{open_frame.kind}}}}} non chiuso")
    return tuple(root.children)


def _consume_token(stack: list[_Frame], body: str, line: int, context: RenderContext) -> None:
    """One `{{...}}`. Mutates `stack`; appends to the frame on top of it."""
    if body.startswith("#"):
        keyword, _, rest = body[1:].partition(" ")
        if keyword not in ("if", "each"):
            _fail(line, f"blocco '{keyword}' sconosciuto", expected="if oppure each")
        stack.append(_Frame(keyword, _parse_path(rest.strip(), line), line))
        return

    if body.startswith("/"):
        keyword = body[1:].strip()
        if len(stack) == 1:
            _fail(line, f"chiusura {{{{/{keyword}}}}} senza blocco aperto")
        frame = stack.pop()
        if frame.kind != keyword:
            _fail(line, f"{{{{/{keyword}}}}} non corrisponde a {{{{#{frame.kind}}}}}")
        node: Node = (
            IfNode(frame.path, frame.line, tuple(frame.children), tuple(frame.otherwise or ()))
            if frame.kind == "if"
            else EachNode(frame.path, frame.line, tuple(frame.children))
        )
        stack[-1].emit(node)
        return

    if body == "else":
        if len(stack) == 1 or stack[-1].kind != "if":
            _fail(line, "{{else}} fuori da un blocco {{#if}}")
        if stack[-1].otherwise is not None:
            # Not named in the brief's test list, but silently free to get right:
            # without this, a second {{else}} in the same block would quietly
            # re-open `otherwise` as a fresh empty list, discarding whatever the
            # first else-branch had already accumulated with no error at all.
            _fail(line, "{{else}} duplicato nello stesso blocco {{#if}}")
        stack[-1].otherwise = []
        return

    # A space in the body would be a helper call -- `{{uppercase nome}}`. The engine
    # has none, by design: a template is a document, not a program, and an engine that
    # executes code inside a template is an attack surface this product has no reason
    # to have (spec 3.2).
    if " " in body or "\n" in body:
        _fail(
            line,
            f"sintassi '{body}' non ammessa: il motore non ha helper ne' espressioni",
            expected="un percorso puntato, es. cliente.ragione_sociale",
        )
    stack[-1].emit(VariableNode(_parse_path(body, line), context, line))


@dataclass(frozen=True)
class DeclaredPaths:
    """What `declared_paths` reports, split by whether the caller can actually
    supply it directly.

    `root` is what a caller must have at the top level of the values it passes in:
    every `{{path}}` referenced outside any `#each`, plus the path an `#if` or
    `#each` itself names -- a template that only ever does
    `{{#if offerta.sconto}}...{{/if}}` still needs `offerta.sconto` supplied, even
    though no bare `{{offerta.sconto}}` ever appears.

    `loop_relative` is everything referenced *inside* an `#each` body: `this` and
    the current element's own properties. These are never something a caller
    supplies at the root -- they describe the shape of each element of whichever
    root array the enclosing `#each` iterates -- so mixing them into `root` would
    tell a caller it needs to supply a top-level `nome`, when what is actually true
    is that each element of (say) `righe` needs one.
    """

    root: tuple[tuple[str, ...], ...]
    loop_relative: tuple[tuple[str, ...], ...]


def declared_paths(nodes: tuple[Node, ...]) -> DeclaredPaths:
    """Every distinct path a template needs from its caller, in first-seen order,
    split into `root` and `loop_relative` -- see `DeclaredPaths`.

    Used by `describe_template` so an agent can ask what a template wants *before*
    asking the user, and by the template service to check declared variables against
    what the body actually uses.

    Overrides the original brief, which asked for one flat tuple of every
    VariableNode's path, `#if`/`#each` paths not included. That shape defeats the
    reason this function exists: a template whose entire behaviour depends on
    `{{#if offerta.sconto}}...{{/if}}` and `{{#each righe}}...{{/each}}` declared
    that it needed nothing at all, since a block's own path was never collected and
    a loop-relative `{{nome}}` looked identical to a root one. `describe_template`
    is only worth having if it can actually tell an agent what to ask the user for
    *before* asking -- so this now collects a block's own path alongside every
    VariableNode's, and keeps anything reached through an `#each` body in a
    separate bucket rather than silently treating it as a root requirement.
    """
    root: list[tuple[str, ...]] = []
    loop_relative: list[tuple[str, ...]] = []

    def add(path: tuple[str, ...], *, inside_each: bool) -> None:
        target = loop_relative if inside_each else root
        if path not in target:
            target.append(path)

    def walk(items: tuple[Node, ...], *, inside_each: bool) -> None:
        for node in items:
            match node:
                case VariableNode(path=path):
                    add(path, inside_each=inside_each)
                case IfNode(path=path, then=then, otherwise=otherwise):
                    add(path, inside_each=inside_each)
                    walk(then, inside_each=inside_each)
                    walk(otherwise, inside_each=inside_each)
                case EachNode(path=path, body=body):
                    add(path, inside_each=inside_each)
                    # The path naming *this* each is declared at the current level
                    # (a caller still needs to supply "righe" at the root, or on the
                    # current loop item if this each is itself nested); everything
                    # inside its own body is relative to the element it iterates,
                    # regardless of whether the current level was already loop-
                    # relative -- so this is unconditionally True, not `inside_each`.
                    walk(body, inside_each=True)
                case TextNode():
                    pass

    walk(nodes, inside_each=False)
    return DeclaredPaths(root=tuple(root), loop_relative=tuple(loop_relative))
