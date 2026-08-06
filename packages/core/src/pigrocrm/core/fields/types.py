from typing import Literal

from pydantic import BaseModel

FieldType = Literal[
    "text",
    "textarea",
    "number",
    "currency",
    "date",
    "select",
    "multiselect",
    "checkbox",
    "url",
]

FIELD_TYPES: tuple[FieldType, ...] = (
    "text",
    "textarea",
    "number",
    "currency",
    "date",
    "select",
    "multiselect",
    "checkbox",
    "url",
)

OPTION_TYPES: frozenset[str] = frozenset({"select", "multiselect"})


class FieldSpec(BaseModel):
    """A field definition, detached from the database row, so the validator stays pure."""

    key: str
    label: str
    field_type: FieldType
    options: list[str] = []
    required: bool = False
