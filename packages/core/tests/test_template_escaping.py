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


def test_markdown_escapes_hash_only_at_the_start_of_a_line() -> None:
    # A "#" mid-sentence is literal in Markdown; one at line start is a heading.
    assert escape_markdown("C# e #hashtag") == r"C# e #hashtag"
    assert escape_markdown("# Titolo") == r"\# Titolo"
    assert escape_markdown("prima\n## Sotto") == "prima\n" + r"\## Sotto"


def test_markdown_escapes_brackets_so_a_name_is_not_a_link() -> None:
    assert escape_markdown("[NOME](http://x)") == r"\[NOME\](http://x)"


def test_typst_escapes_hash_so_an_import_is_not_executed() -> None:
    assert escape_typst(TYPST_INJECTION) == r"\#import \"/etc/passwd\""


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
