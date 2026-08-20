from pigrocrm.core.render.diagnostics import template_line_for, translate_typst_failure

TYPST_SOURCE = """#set page(margin: 1in)

// pigrocrm:line=12
#table(
  columns: (1fr,),
  [#import "x"],
)

// pigrocrm:line=40
#text[ok]
"""

TYPST_STDERR = """error: unexpected keyword `import`
  ┌─ /tmp/pigrocrm-render-abc/intermediate.typ:6:4
  │
6 │   [#import "x"],
  │    ^^^^^^^
"""


def test_template_line_is_the_marker_plus_the_offset_inside_the_block() -> None:
    # Marker on typst line 3 names template line 12, so typst line 6 is template
    # line 12 + (6 - 3 - 1) = 14. Pandoc copies a raw block through verbatim, line
    # for line, which is what makes the arithmetic exact rather than approximate.
    assert template_line_for(TYPST_SOURCE, 6) == 14


def test_template_line_uses_the_nearest_preceding_marker() -> None:
    assert template_line_for(TYPST_SOURCE, 10) == 40


def test_template_line_is_none_before_any_marker() -> None:
    assert template_line_for(TYPST_SOURCE, 1) is None


def test_translate_names_the_template_line_and_the_compiler_message() -> None:
    message = translate_typst_failure(TYPST_STDERR, TYPST_SOURCE)
    assert "riga 14" in message
    assert "unexpected keyword `import`" in message


def test_translate_never_leaks_the_temporary_path() -> None:
    # The path names a directory on the server and is meaningless to the user.
    assert "/tmp/pigrocrm-render-abc" not in translate_typst_failure(TYPST_STDERR, TYPST_SOURCE)


def test_translate_falls_back_when_there_is_no_location() -> None:
    message = translate_typst_failure("error: file not found\n", TYPST_SOURCE)
    assert "file not found" in message
    assert "riga" not in message


def test_translate_falls_back_when_stderr_is_empty() -> None:
    assert "compilazione" in translate_typst_failure("", TYPST_SOURCE)
