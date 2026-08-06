from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, create_model

from pigrocrm.core.fields.types import FieldSpec

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


def python_type_for(spec: FieldSpec) -> Any:
    if spec.field_type == "select":
        return Literal[tuple(spec.options)] if spec.options else str
    if spec.field_type == "multiselect":
        inner = Literal[tuple(spec.options)] if spec.options else str
        return list[inner]  # type: ignore[valid-type]
    return _SIMPLE_TYPES[spec.field_type]


def build_custom_fields_model(entity: str, specs: list[FieldSpec]) -> type[BaseModel]:
    """Turn field definitions into a real Pydantic model at runtime.

    This is the bridge that makes user-defined fields visible to both adapters:
    FastAPI derives OpenAPI from it, and the MCP SDK derives a tool's JSON Schema
    from the function signature it annotates. One source, two descriptions.
    """
    definitions: dict[str, Any] = {}
    for spec in specs:
        annotation = python_type_for(spec)
        if spec.required:
            definitions[spec.key] = (
                Annotated[annotation, Field(description=spec.label)],
                ...,
            )
        else:
            definitions[spec.key] = (
                Annotated[annotation | None, Field(description=spec.label)],
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
