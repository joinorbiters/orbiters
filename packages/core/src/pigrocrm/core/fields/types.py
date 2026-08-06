from typing import Literal, Self

from pydantic import BaseModel, model_validator

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

    @model_validator(mode="after")
    def _choice_types_require_options(self) -> Self:
        """A select/multiselect with no options can never accept a value: every
        rejection would degrade to "uno tra: " with nothing listed - the useless
        "invalid" this design exists to avoid. Refusing to construct the spec is
        better than emitting that message at validation time; the Task 7 service
        also prevents creating such a definition, so this is the second line."""
        if self.field_type in OPTION_TYPES and not self.options:
            raise ValueError(
                f"field_type {self.field_type!r} richiede almeno una opzione in 'options'"
            )
        return self
