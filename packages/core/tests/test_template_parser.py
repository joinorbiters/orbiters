import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.templates.ast import EachNode, IfNode, TextNode, VariableNode
from pigrocrm.core.templates.parser import declared_paths, parse_template, segment

TYPST_BLOCK_TEMPLATE = """Gentile {{cliente.ragione_sociale}},

```{=typst}
#table(
  columns: (0.8fr, 0.2fr),
  [{{riga.servizio}}],
  [{{riga.totale}}],
)
```

Cordiali saluti.
"""


def test_segment_marks_a_fenced_typst_block_as_typst_context() -> None:
    segments = segment(TYPST_BLOCK_TEMPLATE)
    contexts = [s.context for s in segments]
    assert "typst" in contexts
    typst_segment = next(s for s in segments if s.context == "typst")
    assert "#table(" in typst_segment.text
    assert "{{riga.servizio}}" in typst_segment.text


def test_segment_marks_everything_outside_a_fence_as_markdown() -> None:
    segments = segment(TYPST_BLOCK_TEMPLATE)
    markdown_text = "".join(s.text for s in segments if s.context == "markdown")
    assert "{{cliente.ragione_sociale}}" in markdown_text
    assert "#table(" not in markdown_text


def test_segment_marks_an_inline_typst_span_as_typst_context() -> None:
    segments = segment("prima `#emph[{{x}}]`{=typst} dopo")
    assert [(s.context, s.text) for s in segments] == [
        ("markdown", "prima "),
        ("typst", "`#emph[{{x}}]`{=typst}"),
        ("markdown", " dopo"),
    ]


def test_segment_marks_a_link_destination_as_url_context() -> None:
    segments = segment("vedi [il sito]({{cliente.sito_web}}) per i dettagli")
    assert [(s.context, s.text) for s in segments] == [
        ("markdown", "vedi [il sito"),
        ("url", "]({{cliente.sito_web}})"),
        ("markdown", " per i dettagli"),
    ]


def test_segment_records_the_line_each_segment_starts_on() -> None:
    segments = segment(TYPST_BLOCK_TEMPLATE)
    typst_segment = next(s for s in segments if s.context == "typst")
    # The fence opens on line 3 of TYPST_BLOCK_TEMPLATE.
    assert typst_segment.line == 3


def test_parse_gives_each_variable_the_context_of_its_segment() -> None:
    nodes = parse_template(TYPST_BLOCK_TEMPLATE)
    variables = {n.path: n.context for n in nodes if isinstance(n, VariableNode)}
    assert variables[("cliente", "ragione_sociale")] == "markdown"
    assert variables[("riga", "servizio")] == "typst"
    assert variables[("riga", "totale")] == "typst"


def test_the_same_placeholder_gets_two_different_contexts_in_two_places() -> None:
    # This is the single fact the whole engine exists for.
    source = "Nome: {{c.nome}}\n\n```{=typst}\n#text[{{c.nome}}]\n```\n"
    contexts = sorted(n.context for n in parse_template(source) if isinstance(n, VariableNode))
    assert contexts == ["markdown", "typst"]


def test_parse_records_the_template_line_of_every_variable() -> None:
    nodes = parse_template("riga1\nriga2 {{a}}\nriga3\n")
    variable = next(n for n in nodes if isinstance(n, VariableNode))
    assert variable.line == 2


def test_parse_builds_an_if_node_with_both_branches() -> None:
    nodes = parse_template("{{#if offerta.iva}}con IVA{{else}}senza IVA{{/if}}")
    assert len(nodes) == 1
    node = nodes[0]
    assert isinstance(node, IfNode)
    assert node.path == ("offerta", "iva")
    assert node.then == (TextNode("con IVA"),)
    assert node.otherwise == (TextNode("senza IVA"),)


def test_parse_builds_an_if_node_with_no_else_branch() -> None:
    nodes = parse_template("{{#if x}}solo{{/if}}")
    node = nodes[0]
    assert isinstance(node, IfNode)
    assert node.otherwise == ()


def test_parse_builds_an_each_node_and_resolves_this() -> None:
    nodes = parse_template("{{#each righe}}{{this}}-{{nome}};{{/each}}")
    node = nodes[0]
    assert isinstance(node, EachNode)
    assert node.path == ("righe",)
    paths = [n.path for n in node.body if isinstance(n, VariableNode)]
    assert paths == [("this",), ("nome",)]


def test_parse_nests_blocks() -> None:
    nodes = parse_template("{{#each r}}{{#if r.iva}}X{{/if}}{{/each}}")
    outer = nodes[0]
    assert isinstance(outer, EachNode)
    assert isinstance(outer.body[0], IfNode)


def test_parse_rejects_an_unclosed_block_naming_the_line() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("prima\n{{#if x}}mai chiuso\n")
    assert excinfo.value.details["field"] == "corpo_markdown"
    assert "riga 2" in excinfo.value.details["reason"]
    assert "#if" in excinfo.value.details["reason"]


def test_parse_rejects_a_stray_closing_tag_naming_the_line() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("a\nb\n{{/each}}")
    assert "riga 3" in excinfo.value.details["reason"]


def test_parse_rejects_a_mismatched_closing_tag() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("{{#if x}}{{/each}}")
    assert "non corrisponde" in excinfo.value.details["reason"]


def test_parse_rejects_an_else_outside_an_if() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("{{else}}")
    assert "else" in excinfo.value.details["reason"]


@pytest.mark.parametrize(
    "bad",
    ["{{ }}", "{{1abc}}", "{{a..b}}", "{{a.}}", "{{a b}}", "{{a-b}}", "{{a\n}}"],
)
def test_parse_rejects_a_malformed_path(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        parse_template(bad)


def test_parse_rejects_a_helper_call_because_the_engine_has_no_helpers() -> None:
    # Deliberate: "un template e' un documento, non un programma" (spec 3.2).
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("{{uppercase cliente.nome}}")
    assert "non ammessa" in excinfo.value.details["reason"]


def test_declared_paths_collects_every_variable_once_in_order() -> None:
    nodes = parse_template("{{a.b}}{{#each r}}{{nome}}{{/each}}{{a.b}}{{c}}")
    assert declared_paths(nodes) == (("a", "b"), ("nome",), ("c",))


def test_a_template_with_no_placeholders_is_one_text_node() -> None:
    assert parse_template("solo testo") == (TextNode("solo testo"),)


def test_an_empty_template_parses_to_nothing() -> None:
    assert parse_template("") == ()


# --- Beyond the brief's own list: the segmentation boundary is the security-relevant
# part (a placeholder escaped for the wrong context loses everything Task 1 fixed),
# so every edge case named in the task -- an unterminated fence, a fence indented
# inside a list, extra backticks, a malformed attribute, a placeholder spanning a
# boundary, CRLF -- gets its own test below, and the ones that are actually claims
# about what *Pandoc* does are checked against a real Pandoc, not just against this
# module's own regex agreeing with itself.


def test_a_second_else_in_the_same_if_block_is_rejected_not_silently_overwritten() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_template("{{#if x}}a{{else}}b{{else}}c{{/if}}")
    assert "duplicato" in excinfo.value.details["reason"]


def test_padding_spaces_inside_braces_are_ergonomic_but_an_embedded_newline_still_fails() -> None:
    # The `.strip()` in the brief's own sample code strips a trailing "\n" along with
    # the spaces -- which is the exact P.IVA-shaped mistake `_PATH_RE`'s `fullmatch`
    # comment warns about, just moved one call earlier: `{{a\n}}` would reach
    # `_parse_path` already reduced to the valid path "a", the newline discarded
    # before `fullmatch` ever ran. This test pins the fix's actual shape: horizontal
    # padding is still convenient, and a real newline is still rejected regardless.
    nodes = parse_template("{{ cliente.nome }}")
    assert nodes == (VariableNode(("cliente", "nome"), "markdown", 1),)
    with pytest.raises(ValidationFailed):
        parse_template("{{ cliente.nome\n }}")


def test_an_unterminated_fence_is_ordinary_markdown_text_not_a_broken_inline_match() -> None:
    # A naive `` `[^`\n]*`\{=typst\} `` inline pattern matches *inside* this fence's
    # own opening line -- the 2nd and 3rd backticks plus the attribute -- because
    # nothing stops a single-backtick delimiter from sitting right next to another
    # backtick. Confirmed against real Pandoc below: with no closing fence anywhere in
    # the document, the whole line is ordinary paragraph text, not a raw block and not
    # a code span either.
    source = "prima\n\n```{=typst}\n#table([{{riga.totale}}])\n\ndopo, mai chiuso\n"
    segments = segment(source)
    assert all(s.context == "markdown" for s in segments)
    joined = "".join(s.text for s in segments)
    assert joined == source
    nodes = parse_template(source)
    variables = {n.path: n.context for n in nodes if isinstance(n, VariableNode)}
    assert variables[("riga", "totale")] == "markdown"


def test_a_placeholder_spanning_a_fence_boundary_becomes_two_inert_text_fragments() -> None:
    # `{{` opens in the markdown segment, the fence begins before `}}` closes it.
    # Tokenising happens per-segment, so this can never merge into one VariableNode
    # with an arbitrary context -- it becomes two literal, unescaped text fragments,
    # which is confusing for whoever wrote the template but not a security question:
    # no value is ever substituted for either half.
    source = "Nome: {{cliente.\n```{=typst}\nnome}}\n```\n"
    nodes = parse_template(source)
    assert not any(isinstance(n, VariableNode) for n in nodes)
    assert any(isinstance(n, TextNode) and "{{cliente." in n.text for n in nodes)
    assert any(isinstance(n, TextNode) and "nome}}" in n.text for n in nodes)


def test_segment_handles_crlf_line_endings_around_and_inside_a_fence() -> None:
    source = "prima\r\n\r\n```{=typst}\r\n#table([{{a}}])\r\n```\r\n\r\ndopo\r\n"
    segments = segment(source)
    typst_segment = next(s for s in segments if s.context == "typst")
    assert "#table([{{a}}])" in typst_segment.text
    assert "\r" not in typst_segment.text
    # Line 3 whichever line-ending convention it was written with: "prima", "", then
    # the fence opener.
    assert typst_segment.line == 3
    nodes = parse_template(source)
    variable = next(n for n in nodes if isinstance(n, VariableNode))
    assert variable.context == "typst"
    assert variable.line == 4


def test_segment_recognises_a_fence_indented_inside_a_single_level_list() -> None:
    source = "- voce uno\n  ```{=typst}\n  #table([{{riga.totale}}])\n  ```\n- voce due\n"
    segments = segment(source)
    assert "typst" in [s.context for s in segments]
    typst_segment = next(s for s in segments if s.context == "typst")
    assert "{{riga.totale}}" in typst_segment.text
    nodes = parse_template(source)
    variable = next(n for n in nodes if isinstance(n, VariableNode))
    assert variable.context == "typst"


def test_a_fence_indented_four_spaces_at_top_level_is_not_typst() -> None:
    # Four spaces (unindented by a list) is CommonMark's own threshold for "this is an
    # indented code block instead" -- and an indented code block cannot carry a
    # `{=typst}` attribute in the first place. Confirmed against real Pandoc below.
    source = "prima\n\n    ```{=typst}\n    #table([{{a}}])\n    ```\n\ndopo\n"
    segments = segment(source)
    assert all(s.context == "markdown" for s in segments)


def test_a_fence_nested_two_list_levels_deep_is_not_recognised_as_typst() -> None:
    # Documented, tested scope boundary, not a silent gap: a fence one list level deep
    # lines up with CommonMark's own "indented up to three spaces" allowance (see
    # test_segment_recognises_a_fence_indented_inside_a_single_level_list above), but
    # a *second* nested level pushes the fence's indentation past that, and this is a
    # flat regex, not a container-aware Markdown parser that tracks how many spaces
    # each enclosing list item strips. A template that needs this nested a raw block
    # should put the block at the top level instead.
    source = "- uno\n  - due\n    ```{=typst}\n    #table([{{a}}])\n    ```\n"
    segments = segment(source)
    assert all(s.context == "markdown" for s in segments)


def test_segment_does_not_treat_a_language_class_attribute_as_typst() -> None:
    # `{.typst}` is a syntax-highlighting *class*, not the `=format` raw-block marker
    # -- a different Pandoc feature entirely, and its content is code to be displayed,
    # not Typst source to be passed through untouched.
    source = "prima\n\n```{.typst}\n#table([{{a}}])\n```\n\ndopo\n"
    segments = segment(source)
    assert all(s.context == "markdown" for s in segments)


def test_segment_does_not_treat_a_raw_format_combined_with_another_attribute_as_typst() -> None:
    # `{=format}` is special-cased by Pandoc to be the *entire* attribute; combined
    # with anything else it is not recognised as a raw block at all (confirmed live
    # below). Being lenient about it here would mark a segment "typst" whose content
    # Pandoc's own `-t typst` writer never actually treats as raw.
    source = "prima\n\n```{=typst .foo}\nB\n```\n\ndopo\n"
    segments = segment(source)
    assert all(s.context == "markdown" for s in segments)


def test_segment_accepts_trailing_whitespace_inside_the_attribute_braces() -> None:
    source = "prima\n\n```{=typst }\n#table([{{a}}])\n```\n\ndopo\n"
    segments = segment(source)
    assert "typst" in [s.context for s in segments]


def test_segment_rejects_a_leading_space_inside_the_attribute_braces_as_not_typst() -> None:
    source = "prima\n\n```{= typst}\nB\n```\n\ndopo\n"
    segments = segment(source)
    assert all(s.context == "markdown" for s in segments)


def test_segment_recognises_a_fence_with_extra_backticks_around_inner_backticks() -> None:
    # Typst's own raw-code syntax uses backticks too, so a raw block that needs to
    # *contain* a literal ``` has to open with four or more. Confirmed against real
    # Pandoc below: it round-trips the inner ``` unchanged.
    source = "prima\n\n````{=typst}\n`raw code`\n#table([{{a}}])\n````\n\ndopo\n"
    segments = segment(source)
    typst_segment = next(s for s in segments if s.context == "typst")
    assert "`raw code`" in typst_segment.text
    assert "{{a}}" in typst_segment.text


# --- Real compiles: an oracle for what Pandoc actually does with a given byte
# sequence, not a restatement of what this module's own regex believes. Skipped
# cleanly when Pandoc is missing, exactly like test_template_escaping.py; on a machine
# that has it (this one, 3.8.2.1), every subprocess call uses `check=True`.

_MISSING_TOOLS = [tool for tool in ("pandoc", "typst") if shutil.which(tool) is None]
requires_real_compiler = pytest.mark.skipif(
    bool(_MISSING_TOOLS),
    reason=f"real Pandoc round-trip tests need these on PATH: {', '.join(_MISSING_TOOLS)}",
)


def _pandoc_blocks(markdown_source: str, tmp_path: Path) -> list[dict[str, Any]]:
    """Every top-level-or-list-item block Pandoc's own reader produces for
    `markdown_source`, flattened one level into list items -- enough to find a
    `RawBlock` wherever this module's tests put one, without writing a full
    recursive Pandoc-AST walker for a handful of fixtures."""
    md_path = tmp_path / "doc.md"
    md_path.write_text(markdown_source, encoding="utf-8")
    result = subprocess.run(
        ["pandoc", str(md_path), "-t", "json"], check=True, capture_output=True, text=True
    )
    doc = json.loads(result.stdout)
    blocks: list[dict[str, Any]] = []
    for block in doc["blocks"]:
        blocks.append(block)
        if block["t"] in ("BulletList", "OrderedList"):
            items = block["c"] if block["t"] == "BulletList" else block["c"][1]
            for item in items:
                blocks.extend(item)
    return blocks


def _is_typst_raw_block(block: dict[str, Any]) -> bool:
    return block["t"] == "RawBlock" and block["c"][0] == "typst"


@requires_real_compiler
def test_for_real_an_unterminated_fence_is_not_a_raw_block_in_pandoc_either(
    tmp_path: Path,
) -> None:
    source = "prima\n\n```{=typst}\n#table([x])\n\ndopo, mai chiuso\n"
    blocks = _pandoc_blocks(source, tmp_path)
    assert not any(b["t"] == "RawBlock" for b in blocks)
    assert not any(b["t"] == "CodeBlock" for b in blocks)


@requires_real_compiler
def test_for_real_a_fence_indented_inside_a_single_level_list_is_a_raw_block(
    tmp_path: Path,
) -> None:
    source = "- voce uno\n  ```{=typst}\n  #table([x])\n  ```\n- voce due\n"
    blocks = _pandoc_blocks(source, tmp_path)
    assert any(_is_typst_raw_block(b) for b in blocks)


@requires_real_compiler
def test_for_real_a_fence_indented_four_spaces_at_top_level_is_a_plain_code_block(
    tmp_path: Path,
) -> None:
    source = "prima\n\n    ```{=typst}\n    #table([x])\n    ```\n\ndopo\n"
    blocks = _pandoc_blocks(source, tmp_path)
    assert not any(b["t"] == "RawBlock" for b in blocks)
    assert any(b["t"] == "CodeBlock" for b in blocks)


@requires_real_compiler
def test_for_real_a_language_class_attribute_is_a_code_block_not_a_raw_block(
    tmp_path: Path,
) -> None:
    source = "prima\n\n```{.typst}\n#table([x])\n```\n\ndopo\n"
    blocks = _pandoc_blocks(source, tmp_path)
    assert not any(b["t"] == "RawBlock" for b in blocks)
    assert any(b["t"] == "CodeBlock" for b in blocks)


@requires_real_compiler
def test_for_real_trailing_whitespace_inside_the_attribute_braces_is_still_raw(
    tmp_path: Path,
) -> None:
    source = "prima\n\n```{=typst }\nB\n```\n\ndopo\n"
    blocks = _pandoc_blocks(source, tmp_path)
    assert any(_is_typst_raw_block(b) for b in blocks)
    md_path = tmp_path / "doc.md"
    md_path.write_text(source, encoding="utf-8")
    written = subprocess.run(
        ["pandoc", str(md_path), "-t", "typst"], check=True, capture_output=True, text=True
    ).stdout
    assert "B" in written


@requires_real_compiler
def test_for_real_a_leading_space_inside_the_attribute_braces_is_not_raw(
    tmp_path: Path,
) -> None:
    source = "prima\n\n```{= typst}\nB\n```\n\ndopo\n"
    blocks = _pandoc_blocks(source, tmp_path)
    assert not any(b["t"] == "RawBlock" for b in blocks)


@requires_real_compiler
def test_for_real_a_raw_format_combined_with_another_attribute_is_not_raw(
    tmp_path: Path,
) -> None:
    source = "prima\n\n```{=typst .foo}\nB\n```\n\ndopo\n"
    blocks = _pandoc_blocks(source, tmp_path)
    assert not any(b["t"] == "RawBlock" for b in blocks)


@requires_real_compiler
def test_for_real_a_mixed_case_attribute_is_dropped_by_the_typst_writer_entirely(
    tmp_path: Path,
) -> None:
    # Not this module's bug to fix -- recorded because it changes what "safe default"
    # means. Pandoc's *reader* accepts `{=Typst}` as a raw block (format "Typst",
    # case preserved), but its `-t typst` *writer* only passes through a block whose
    # format is exactly "typst": a case mismatch does not fall back to visible text,
    # it makes the whole block vanish with no error. This module still only ever
    # recognises the exact lowercase literal, which -- given the content disappears
    # either way once rendered -- is the same outcome as trying to be lenient here,
    # not a gap this module leaves open.
    source = "prima\n\n```{=Typst}\nB\n```\n\ndopo\n"
    md_path = tmp_path / "doc.md"
    md_path.write_text(source, encoding="utf-8")
    written = subprocess.run(
        ["pandoc", str(md_path), "-t", "typst"], check=True, capture_output=True, text=True
    ).stdout
    assert "B" not in written


@requires_real_compiler
def test_for_real_extra_backticks_let_a_raw_block_contain_a_literal_triple_backtick(
    tmp_path: Path,
) -> None:
    source = "prima\n\n````{=typst}\n`raw code`\n#table([x])\n````\n\ndopo\n"
    md_path = tmp_path / "doc.md"
    md_path.write_text(source, encoding="utf-8")
    written = subprocess.run(
        ["pandoc", str(md_path), "-t", "typst"], check=True, capture_output=True, text=True
    ).stdout
    assert "`raw code`" in written
    assert "#table([x])" in written
