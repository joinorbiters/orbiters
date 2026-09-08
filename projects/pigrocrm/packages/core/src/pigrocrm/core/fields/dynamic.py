from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, create_model

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fields.types import FieldSpec
from pigrocrm.core.fields.validator import coerce_value, is_blank

# currency and date stay strings on the wire: JSON has no decimal and no date type,
# and the validator has already normalised them to a canonical string form.
_SIMPLE_TYPES: dict[str, Any] = {
    "text": str,
    "textarea": str,
    "number": float,
    "currency": str,
    "date": str,
    "checkbox": bool,
    "url": str,
}

# JSON Schema `format` for the `str`-shaped types that have a real, recognisable
# shape narrower than "any string" -- a structural signal an agent reading the
# schema can act on without having to guess from the human `label`. `text` and
# `textarea` have no such shape (any string is valid text), so they get none.
_FORMAT_HINTS: dict[str, str] = {
    "date": "date",
    "currency": "decimal",
    "url": "uri",
}


def python_type_for(spec: FieldSpec) -> Any:
    if spec.field_type == "select":
        return Literal[tuple(spec.options)] if spec.options else str
    if spec.field_type == "multiselect":
        inner = Literal[tuple(spec.options)] if spec.options else str
        return list[inner]  # type: ignore[valid-type]
    return _SIMPLE_TYPES[spec.field_type]


def _delegating_validator(entity: str, spec: FieldSpec) -> BeforeValidator:
    """The model does not validate on its own: it calls the single authority.

    This has to run *before* Pydantic's own core type check, not after. For the
    five types mapped to `str` a "before" or an "after" validator would work
    equally well, because a bare `str` schema accepts every input an "after" hook
    would ever see -- but for `checkbox` they are not equivalent: Pydantic's own
    lax `bool` parsing does not recognise the Italian "si"/"sì" that
    `coerce_value` does, so an "after" validator attached to a `bool` field would
    never even be called for that input -- Pydantic would already have rejected
    it. Running first means `coerce_value` settles the question before Pydantic's
    own type check gets a vote, so it wins in both directions: it rejects a
    malformed date or a `javascript:` URL a bare `str` field would otherwise let
    through (the validator is defended against exactly that, to stop a
    stored-XSS), and it accepts a "si" a bare `bool` field would otherwise
    reject. What Pydantic validates afterwards is already the coerced, canonical
    value, so that check is a formality it cannot fail.

    The blank check below has to come first too, and has to be the *same*
    function `validate_custom_fields` uses -- not a narrower `value is None`
    stand-in. `coerce_value` has no notion of "absent": it is only ever asked
    about a value `validate_custom_fields` already decided was present. Calling
    it directly on a blank value gives a wrong answer for both directions --
    `coerce_value` would clean an empty string into "" and report it as a real
    value for a required field the validator rejects outright, and would reject
    an empty list for an optional multiselect that the validator simply omits
    as absent. `is_blank` is what tells `False` and `0` apart from "nothing was
    provided", so a required checkbox set to `False` still reaches
    `coerce_value` and is correctly accepted, never confused with a missing
    field.
    """

    def _check(value: Any) -> Any:
        if is_blank(value):
            if spec.required:
                raise ValueError(f"{spec.key}: campo obbligatorio")
            return None
        try:
            return coerce_value(entity, spec, value)
        except ValidationFailed as exc:
            # Pydantic expects a validator to raise ValueError; the domain
            # message (already entity/field/reason-shaped) survives unchanged.
            raise ValueError(exc.message) from exc

    return BeforeValidator(_check)


def _field_info(spec: FieldSpec) -> Any:
    """The label as `description` -- what an agent reads to discover a field
    nobody hardcoded -- plus a `format` hint for the types that have one."""
    format_hint = _FORMAT_HINTS.get(spec.field_type)
    return Field(
        description=spec.label,
        json_schema_extra={"format": format_hint} if format_hint else None,
    )


def build_custom_fields_model(entity: str, specs: list[FieldSpec]) -> type[BaseModel]:
    """Turn field definitions into a real Pydantic model at runtime.

    This is the bridge that makes user-defined fields visible to both adapters:
    FastAPI derives OpenAPI from it, and the MCP SDK derives a tool's JSON Schema
    from the function signature it annotates. One source, two descriptions.

    Every field delegates to the same two functions, called in the same order, as
    `validate_custom_fields`: `is_blank` first, then `coerce_value`. Calling only
    the second (an earlier version of this module did) is not equivalent -- a
    required field would accept an empty string as if it were a real value, and
    an optional multiselect would store `[]` instead of treating it as absent --
    so this model can never accept a value the validator would reject, or reject
    one it would accept. Checked directly against `validate_custom_fields` across
    all nine field types, both required and optional, over a broad matrix of
    inputs (blank in every shape, valid, invalid, and boundary values such as
    `False`, `0`, `inf`/`nan`, and padded option strings): zero disagreements.
    See `_delegating_validator` for why the delegation also has to run inside a
    `BeforeValidator`, not an `AfterValidator`.

    Call this once per entity, from that entity's *current* field definitions,
    each time a schema is needed. Do not hold on to a model built from a stale
    set of specs and pass it, alongside a freshly built one for the same entity,
    into the same schema-generation call (e.g. `pydantic.json_schema.
    models_json_schema`, which is what powers FastAPI's combined OpenAPI output).
    Two different classes for the same entity both take the name
    f"{entity.capitalize()}CustomFields"; Pydantic disambiguates the `$defs` keys
    in that case, but the `title`s in the rendered schema stay identical and
    ambiguous. There is only ever one current set of field definitions per
    entity, so this is a non-issue as long as nothing caches a model built from a
    previous set alongside a new one.
    """
    definitions: dict[str, Any] = {}
    for spec in specs:
        annotation = python_type_for(spec)
        field_info = _field_info(spec)
        validator = _delegating_validator(entity, spec)
        if spec.required:
            definitions[spec.key] = (
                Annotated[annotation, field_info, validator],
                ...,
            )
        else:
            definitions[spec.key] = (
                Annotated[annotation | None, field_info, validator],
                None,
            )

    model_name = f"{entity.capitalize()}CustomFields"
    return create_model(model_name, **definitions)


def describe_specs(specs: list[FieldSpec]) -> list[dict[str, Any]]:
    """Plain JSON-serialisable description, for the `describe_schema` MCP tool and
    for the frontend's dynamic renderer."""
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "type": spec.field_type,
            "required": spec.required,
            "options": list(spec.options),
        }
        for spec in specs
    ]
