from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from pigrocrm.core.fields.dynamic import build_custom_fields_model, describe_specs
from pigrocrm.core.fields.types import FieldSpec


def spec(key: str, field_type: str, **kw: Any) -> FieldSpec:
    return FieldSpec(key=key, label=key.title(), field_type=field_type, **kw)  # type: ignore[arg-type]


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
