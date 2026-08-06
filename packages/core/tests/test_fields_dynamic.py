from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from pigrocrm.core.errors import ValidationFailed
from pigrocrm.core.fields.dynamic import build_custom_fields_model, describe_specs
from pigrocrm.core.fields.types import FieldSpec
from pigrocrm.core.fields.validator import validate_custom_fields


def spec(key: str, field_type: str, **kw: Any) -> FieldSpec:
    return FieldSpec(key=key, label=key.title(), field_type=field_type, **kw)  # type: ignore[arg-type]


def _try_validate(entity: str, s: FieldSpec, value: Any) -> tuple[bool, Any]:
    """(accepted, normalised_value) for the single validation authority."""
    try:
        return True, validate_custom_fields(entity, [s], {s.key: value})[s.key]
    except ValidationFailed:
        return False, None


def _try_model(model: type[BaseModel], key: str, value: Any) -> tuple[bool, Any]:
    """(accepted, normalised_value) for the runtime model."""
    try:
        return True, model(**{key: value}).model_dump()[key]
    except ValidationError:
        return False, None


def test_no_specs_produces_an_empty_but_valid_model() -> None:
    model = build_custom_fields_model("customer", [])
    assert issubclass(model, BaseModel)
    assert model().model_dump() == {}


def test_the_model_name_mentions_the_entity() -> None:
    model = build_custom_fields_model("customer", [spec("settore", "text")])
    assert "Customer" in model.__name__


def test_optional_fields_default_to_none() -> None:
    model = build_custom_fields_model("customer", [spec("settore", "text")])
    assert model().settore is None  # type: ignore[attr-defined]


def test_required_fields_are_required() -> None:
    model = build_custom_fields_model("customer", [spec("settore", "text", required=True)])
    with pytest.raises(ValidationError):
        model()


def test_json_schema_exposes_every_key_with_its_label_as_description() -> None:
    """This is what an agent reads to discover a field nobody hardcoded."""
    specs = [spec("settore", "text"), spec("budget", "currency")]
    schema = build_custom_fields_model("customer", specs).model_json_schema()

    assert set(schema["properties"]) == {"settore", "budget"}
    assert schema["properties"]["settore"]["description"] == "Settore"


def test_select_becomes_an_enum_in_the_json_schema() -> None:
    """An enum is what lets the model pick a valid option instead of guessing."""
    s = spec("stato", "select", options=["attivo", "sospeso"])
    schema = build_custom_fields_model("customer", [s]).model_json_schema()
    rendered = str(schema)
    assert "attivo" in rendered and "sospeso" in rendered


def test_multiselect_becomes_an_array() -> None:
    s = spec("tag", "multiselect", options=["a", "b"])
    schema = build_custom_fields_model("customer", [s]).model_json_schema()
    prop = schema["properties"]["tag"]
    assert "array" in str(prop)


@pytest.mark.parametrize(
    ("field_type", "value"),
    [
        ("text", "IT"),
        ("textarea", "riga\nriga"),
        ("number", 5.5),
        ("currency", "1234.56"),
        ("date", "2026-08-06"),
        ("checkbox", True),
        ("url", "https://example.com"),
    ],
)
def test_each_type_round_trips_a_valid_value(field_type: str, value: Any) -> None:
    model = build_custom_fields_model("customer", [spec("campo", field_type)])
    assert model(campo=value).model_dump()["campo"] == value


def test_checkbox_rejects_a_non_boolean() -> None:
    model = build_custom_fields_model("customer", [spec("ok", "checkbox")])
    with pytest.raises(ValidationError):
        model(ok="forse")


def test_describe_specs_returns_plain_serialisable_data() -> None:
    import json

    specs = [spec("stato", "select", options=["attivo"], required=True)]
    described = describe_specs(specs)

    assert described == [
        {
            "key": "stato",
            "label": "Stato",
            "type": "select",
            "required": True,
            "options": ["attivo"],
        }
    ]
    json.dumps(described)  # must not raise


def test_two_entities_produce_independent_models() -> None:
    a = build_custom_fields_model("customer", [spec("uno", "text")])
    b = build_custom_fields_model("deal", [spec("due", "text")])
    assert set(a.model_fields) == {"uno"}
    assert set(b.model_fields) == {"due"}


@pytest.mark.parametrize(
    ("field_type", "value"),
    [
        ("date", "06/08/2026"),
        ("date", "domani"),
        ("currency", "hello"),
        ("url", "javascript:alert(1)"),
        ("url", "example.com"),
        ("checkbox", "si"),
    ],
)
def test_model_and_validator_agree_on_previously_divergent_inputs(
    field_type: str, value: Any
) -> None:
    """A line-by-line comparison of `build_custom_fields_model` against
    `validate_custom_fields` found exactly these six inputs disagreeing: the model
    was more permissive than the validator on date/currency/url -- a bare `str`
    annotation carries no format constraint of its own, so it let through a
    malformed date, a non-numeric currency, and (worst of all) a `javascript:` URL
    the validator rejects specifically to stop a stored-XSS -- and stricter on
    checkbox, because pydantic's own lax `bool` parsing does not recognise the
    Italian "si" that `coerce_value` does. Either both reject, or both accept and
    produce the identical normalised value. Two authorities that can disagree is
    exactly what this module exists to prevent."""
    s = spec("campo", field_type)
    model = build_custom_fields_model("customer", [s])

    validator_accepted, validator_value = _try_validate("customer", s, value)
    model_accepted, model_value = _try_model(model, "campo", value)

    assert model_accepted == validator_accepted, (
        f"{field_type}={value!r}: validator accepted={validator_accepted}, "
        f"model accepted={model_accepted}"
    )
    if validator_accepted:
        assert model_value == validator_value


def test_currency_is_normalised_by_the_model_exactly_like_the_validator() -> None:
    """Delegating is not just a reject/accept gate: the model must also produce the
    same normalised wire value, not pass the raw input through unchanged."""
    s = spec("budget", "currency")
    model = build_custom_fields_model("customer", [s])
    assert model(budget="1234.567").model_dump()["budget"] == "1234.57"


@pytest.mark.parametrize(
    ("field_type", "expected_format"),
    [("date", "date"), ("currency", "decimal"), ("url", "uri")],
)
def test_types_with_a_recognisable_shape_carry_a_format_hint(
    field_type: str, expected_format: str
) -> None:
    """text, textarea, currency, date and url all render as a bare
    `{"type": "string"}` in the JSON Schema -- structurally indistinguishable. An
    agent reading the schema (not the human `label`) needs a signal that tells it
    to send "2026-08-06", not "domani". `format` is that signal."""
    model = build_custom_fields_model("customer", [spec("campo", field_type)])
    prop = model.model_json_schema()["properties"]["campo"]
    assert prop["format"] == expected_format


def test_text_and_textarea_carry_no_format_hint() -> None:
    """Unlike date/currency/url, plain text has no shape narrower than "a string" --
    asserting the absence guards against a future edit adding a misleading one."""
    for field_type in ("text", "textarea"):
        model = build_custom_fields_model("customer", [spec("campo", field_type)])
        prop = model.model_json_schema()["properties"]["campo"]
        assert "format" not in prop
