"""R13, written in its correct form instead of the promise that has now been
disproved three times: **the database is open** (`field_definitions.entity_type` is
`String(30)` with no constraint), **the type is extended in four places** --
`fields/schemas.py:EntityType`, `schema_registry.py:ENTITY_TYPES` and
`CREATE_MODELS`, and `apps/web/src/lib/schema.ts:EntityType` -- **and no migration
is needed.** This test is the four places, asserted.

`EXPECTED` includes `invoice`: the plan's own brief for this task listed only the
four pre-invoicing entity types plus the two new ones, but `invoice` is already a
real, shipped `EntityType` member (the invoicing slice added it) -- dropping it here
would have silently regressed `EntityType`, `ENTITY_TYPES` and `CREATE_MODELS` back
to five members instead of widening them to seven.
"""

import re
from pathlib import Path

from pigrocrm.core.documents.schemas import DocumentTipo
from pigrocrm.core.fields.schemas import EntityType
from pigrocrm.core.schema_registry import CREATE_MODELS, ENTITY_TYPES, native_fields

WEB_SCHEMA = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib" / "schema.ts"

EXPECTED = ("customer", "person", "deal", "document", "invoice", "time_entry", "cost")


def test_entity_type_literal_covers_this_slice() -> None:
    assert set(EntityType.__args__) == set(EXPECTED)


def test_registry_agrees_with_the_literal() -> None:
    assert set(ENTITY_TYPES) == set(EXPECTED)
    assert set(CREATE_MODELS) == set(EXPECTED)


def test_native_fields_names_this_slice_columns() -> None:
    """The names A13 (Task 4A-2) has to defend. Asserted here so that renaming a
    column without revisiting the guard's own test still trips something."""
    assert {"ore", "data", "descrizione"} <= set(native_fields("time_entry"))
    assert {"importo", "data", "descrizione"} <= set(native_fields("cost"))


def test_document_tipo_gained_the_time_report() -> None:
    assert "rapporto_ore" in DocumentTipo.__args__


def test_the_frontend_literal_agrees() -> None:
    """`re.fullmatch`, not `re.match` with `$`, per the standing project rule -- and
    here it also matters: the union spans one line and a `$` would match before a
    trailing newline inside the file."""
    source = WEB_SCHEMA.read_text(encoding="utf-8")
    match = re.search(r"export type EntityType =([^\n]+)\n", source)
    assert match is not None, "EntityType not found in apps/web/src/lib/schema.ts"
    declared = {part.strip().strip("'") for part in match.group(1).split("|")}
    assert declared == set(EXPECTED)
