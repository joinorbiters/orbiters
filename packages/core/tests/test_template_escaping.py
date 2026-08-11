import shutil
import string
import subprocess
from pathlib import Path

import pytest

from pigrocrm.core.templates.escaping import (
    escape_for,
    escape_markdown,
    escape_typst,
    escape_url,
)

# The two adversarial values the spec names (§3.3, "Test di accettazione"). Every
# assertion below is about one of these two reaching the page as the literal text
# somebody typed, in whichever of the two contexts it lands in.
TYPST_INJECTION = '#import "/etc/passwd"'
MARKDOWN_INJECTION = "**Grassetto** & <script>"


def test_markdown_escapes_emphasis_so_it_is_not_bold() -> None:
    assert escape_markdown(MARKDOWN_INJECTION) == r"\*\*Grassetto\*\* \& \<script\>"


def test_markdown_escapes_the_backslash_first_and_only_once() -> None:
    # If "\" were escaped after the others, the backslash this function itself
    # introduced would be escaped again and the output would double for every pass.
    assert escape_markdown(r"a\*b") == r"a\\\*b"


def test_markdown_escapes_hash_unconditionally_not_only_at_line_start() -> None:
    # Fix round 1: the first version of this function escaped "#" only at the start
    # of a line (an ATX heading is only syntax there). A reviewer's own compiles
    # showed the curated-character-list design this depended on missed "/" and "@"
    # entirely (see below); the replacement escapes every ASCII punctuation
    # character unconditionally, "#" included. That is simpler and no less correct
    # for "#" specifically: a backslash-escaped "#" mid-sentence round-trips through
    # Pandoc to the identical bare "#" leaving it alone would have produced --
    # confirmed live in test_hash_at_paragraph_start_does_not_become_a_heading below.
    assert escape_markdown("C# e #hashtag") == r"C\# e \#hashtag"
    assert escape_markdown("# Titolo") == r"\# Titolo"


def test_markdown_escapes_brackets_so_a_name_is_not_a_link() -> None:
    assert escape_markdown("[NOME](http://x)") == r"\[NOME\]\(http\:\/\/x\)"


def test_typst_escapes_hash_so_an_import_is_not_executed() -> None:
    assert escape_typst(TYPST_INJECTION) == r"\#import \"\/etc\/passwd\""


def test_typst_escapes_at_dollar_and_angle_brackets() -> None:
    assert escape_typst("a@b $x$ <lab>") == r"a\@b \$x\$ \<lab\>"


def test_typst_escapes_brackets_that_would_close_a_content_block() -> None:
    # A raw {=typst} table cell is written as [ ... ]; an unbalanced "]" in a value
    # ends the cell early and the document stops compiling with a syntax error that
    # points at the template, not at the data.
    assert escape_typst("costo [IVA]") == r"costo \[IVA\]"


def test_typst_collapses_newlines_to_a_space() -> None:
    # A value lands inside a syntactic unit (a table cell, a header field). Keeping a
    # raw newline changes the layout of a document nobody proof-read; a space does not.
    assert escape_typst("riga1\nriga2") == "riga1 riga2"
    assert escape_typst("riga1\r\nriga2") == "riga1 riga2"


def test_typst_escapes_the_backslash_first_and_only_once() -> None:
    assert escape_typst(r"a\#b") == r"a\\\#b"


def test_url_percent_encodes_everything_unsafe() -> None:
    assert escape_url("a b/c?d=e&f") == "a%20b%2Fc%3Fd%3De%26f"
    assert escape_url(TYPST_INJECTION) == "%23import%20%22%2Fetc%2Fpasswd%22"


def test_escape_for_dispatches_on_context() -> None:
    assert escape_for("markdown", MARKDOWN_INJECTION) == escape_markdown(MARKDOWN_INJECTION)
    assert escape_for("typst", TYPST_INJECTION) == escape_typst(TYPST_INJECTION)
    assert escape_for("url", "a b") == escape_url("a b")


def test_escape_for_rejects_an_unknown_context() -> None:
    with pytest.raises(ValueError, match="contesto di escaping sconosciuto"):
        escape_for("latex", "x")  # type: ignore[arg-type]


def test_a_nul_byte_is_rejected_not_stripped_in_every_context() -> None:
    # Same rule as pigrocrm.core.validation.SafeStr: silently deleting one invisible
    # byte from a user's text is a lost character nobody notices.
    for escaper in (escape_markdown, escape_typst, escape_url):
        with pytest.raises(ValueError, match="carattere nullo"):
            escaper("a\x00b")


def test_escaping_is_idempotent_in_meaning_not_in_text() -> None:
    # Escaping twice must not silently produce the same string as escaping once --
    # if it did, a double-escape bug would be invisible. This test exists to make
    # that failure loud if anyone "optimises" the escapers into being idempotent.
    once = escape_markdown("*x*")
    assert escape_markdown(once) != once


def test_every_ascii_punctuation_character_is_escaped_in_both_contexts() -> None:
    # Fix round 1: a reviewer compiled real PDFs against the first version and got
    # two Criticals through with ordinary data, not the two adversarial strings this
    # file names. escape_typst had "@" and escape_markdown did not; neither had "/",
    # and a bare "//" opens a Typst line comment -- a customer named "Rossi // nota"
    # deleted the rest of that line, including a VAT clause, from a real, cleanly
    # compiled PDF, no error. Two independently hand-curated lists drift apart from
    # each other for the same reason one list drifts from correct over time: nothing
    # forces either to be complete. This test asserts the property that replaces
    # both lists: every one of the 32 ASCII punctuation characters is escaped, in
    # both contexts, unconditionally -- not just the ones a previous bug report
    # happened to name.
    for ch in string.punctuation:
        assert escape_markdown(ch) == "\\" + ch, ch
        assert escape_typst(ch) == "\\" + ch, ch


def test_newline_equivalents_all_collapse_to_one_space_in_both_contexts() -> None:
    # Fix round 1: _ANY_NEWLINE (now _NEWLINE_EQUIVALENTS) caught \r\n, \r and \n but
    # missed five characters Typst's own lexer also treats as a line terminator --
    # U+000B, U+000C, U+0085, U+2028 and U+2029. Pandoc's Markdown reader does not
    # recognise any of the five as line-structuring whitespace, so it passed one
    # through a value untouched, straight into the compiled Typst source as a literal
    # code point -- where Typst's lexer does treat it as a real line break. Confirmed
    # live: "Rossi" + U+2028 + "= TITOLO INIETTATO" compiled to a genuine heading, in
    # both contexts, before this fix.
    exotic_newlines = ["\v", "\f", "\x85", chr(0x2028), chr(0x2029), "\r\n", "\r", "\n"]
    for newline in exotic_newlines:
        value = "a" + newline + "b"
        assert escape_markdown(value) == "a b", repr(newline)
        assert escape_typst(value) == "a b", repr(newline)


# --- Real compiles: the test that matters is the property, not the two characters a
# bug report happened to name. Guarded rather than required: nothing in this project
# has ever shelled out to an external binary before this module, so there is no
# existing convention to follow, and this repository's own CI does not install Pandoc
# or Typst today. Skipping cleanly when either (or `pdftotext`, used to read the
# compiled PDF back as text) is missing keeps the suite honest on a machine that lacks
# them, rather than failing for a reason that has nothing to do with this module. On a
# machine that DOES have them -- this one, Pandoc 3.8.2.1 and Typst 0.14.2 confirmed --
# every `subprocess.run` below uses `check=True`: a real compile error is a test
# failure, never something the skip is allowed to quietly absorb instead.

_MISSING_TOOLS = [tool for tool in ("pandoc", "typst", "pdftotext") if shutil.which(tool) is None]
requires_real_compiler = pytest.mark.skipif(
    bool(_MISSING_TOOLS),
    reason=f"real Pandoc/Typst round-trip tests need these on PATH: {', '.join(_MISSING_TOOLS)}",
)


def _compile_markdown_paragraph_to_pdf_text(body_markdown: str, tmp_path: Path) -> str:
    """One line of Markdown body text through the real two-stage pipeline this
    project uses -- Pandoc's own Typst *writer* (`-t typst`), not `--pdf-engine`,
    which needs a font this host does not always resolve for Pandoc's default
    standalone template; unrelated to escaping, noted in the task report -- then
    `typst compile`, then `pdftotext` to read the rendered PDF back as text.
    """
    md_path = tmp_path / "doc.md"
    typst_path = tmp_path / "doc.typst"
    pdf_path = tmp_path / "doc.pdf"
    md_path.write_text(body_markdown + "\n", encoding="utf-8")
    subprocess.run(["pandoc", str(md_path), "-t", "typst", "-o", str(typst_path)], check=True)
    subprocess.run(["typst", "compile", str(typst_path), str(pdf_path)], check=True)
    extracted = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"], check=True, capture_output=True, text=True
    )
    return extracted.stdout


def _compile_typst_markup_to_pdf_text(markup: str, tmp_path: Path) -> str:
    """`markup` -- already-escaped Typst source, exactly as it would appear inside a
    raw ```{=typst} block -- straight through `typst compile`, no Pandoc involved:
    `escape_typst`'s own contract is that its output IS the final Typst source.
    """
    typst_path = tmp_path / "doc.typst"
    pdf_path = tmp_path / "doc.pdf"
    typst_path.write_text(markup + "\n", encoding="utf-8")
    subprocess.run(["typst", "compile", str(typst_path), str(pdf_path)], check=True)
    extracted = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"], check=True, capture_output=True, text=True
    )
    return extracted.stdout


@requires_real_compiler
def test_every_ascii_punctuation_character_survives_markdown_context_for_real(
    tmp_path: Path,
) -> None:
    payload = string.punctuation
    escaped = escape_markdown(payload)
    text = _compile_markdown_paragraph_to_pdf_text(f"X{escaped}Y", tmp_path)
    assert f"X{payload}Y" in text


@requires_real_compiler
def test_every_ascii_punctuation_character_survives_typst_context_for_real(
    tmp_path: Path,
) -> None:
    payload = string.punctuation
    escaped = escape_typst(payload)
    text = _compile_typst_markup_to_pdf_text(f"X{escaped}Y", tmp_path)
    assert f"X{payload}Y" in text


@requires_real_compiler
def test_c1_slash_no_longer_opens_a_typst_line_comment(tmp_path: Path) -> None:
    # The first Critical: escape_typst did not escape "/", and "//" is a Typst line
    # comment. A customer name of "Rossi // nota" used to delete the rest of the
    # line -- here, a VAT clause -- from a real, cleanly compiled PDF, no error.
    hostile = "Rossi // nota"
    escaped = escape_typst(hostile)
    markup = f"#block[\n  Cliente: {escaped}\n  Validita 15 giorni\n]\n"
    text = _compile_typst_markup_to_pdf_text(markup, tmp_path)
    assert hostile in text
    assert "Validita 15 giorni" in text


@requires_real_compiler
def test_c2_at_sign_no_longer_becomes_a_pandoc_citation(tmp_path: Path) -> None:
    # The mirror Critical: escape_markdown did not escape "@", and Pandoc reads an
    # unescaped "@word" as a citation -- the build used to die with "the document
    # does not contain a bibliography" instead of ever producing a PDF at all.
    hostile = "Contatto @rossi2024 urgente"
    escaped = escape_markdown(hostile)
    text = _compile_markdown_paragraph_to_pdf_text(escaped, tmp_path)
    assert hostile in text


@requires_real_compiler
def test_hash_at_paragraph_start_does_not_become_a_heading(tmp_path: Path) -> None:
    escaped = escape_markdown("# Titolo Iniettato")
    text = _compile_markdown_paragraph_to_pdf_text(escaped, tmp_path)
    assert "# Titolo Iniettato" in text


@requires_real_compiler
def test_u2028_no_longer_manufactures_a_heading_in_markdown_context(tmp_path: Path) -> None:
    hostile = "Rossi" + chr(0x2028) + "= TITOLO INIETTATO"
    escaped = escape_markdown(hostile)
    text = _compile_markdown_paragraph_to_pdf_text(escaped, tmp_path)
    assert "Rossi = TITOLO INIETTATO" in text


@requires_real_compiler
def test_u2028_no_longer_manufactures_a_heading_in_typst_context(tmp_path: Path) -> None:
    hostile = "Rossi" + chr(0x2028) + "= TITOLO INIETTATO"
    escaped = escape_typst(hostile)
    text = _compile_typst_markup_to_pdf_text(f"#block[{escaped}]", tmp_path)
    assert "Rossi = TITOLO INIETTATO" in text


@requires_real_compiler
def test_known_limitation_typst_own_ligature_still_alters_repeated_dash_in_markdown(
    tmp_path: Path,
) -> None:
    """Documented in the module docstring, demonstrated here rather than only
    asserted, the same way test_architecture.py pins its own known gap. Not closed
    by this module: escape_markdown's escaping never reaches past Pandoc's own Typst
    *writer*, which re-serialises parsed text on its own rules and does not defend a
    lone "-" the way it defends "$" or "~". Two of them survive Pandoc's round trip
    as separate, individually harmless characters and only become adjacent again in
    Typst's own compiled input, where Typst's lexer -- independent of Pandoc -- merges
    them into an en dash. escape_typst does not share this problem: see
    test_every_ascii_punctuation_character_survives_typst_context_for_real above,
    where an escaped "-" reaches Typst already protected because nothing
    re-serialises escape_typst's output.
    """
    escaped = escape_markdown("Rossi -- Bianchi")
    text = _compile_markdown_paragraph_to_pdf_text(escaped, tmp_path)
    assert "Rossi – Bianchi" in text  # en dash: the residual gap, not the fix
