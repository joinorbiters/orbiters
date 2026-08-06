import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from pigrocrm.core.fields.types import FieldType

# Open by design: later slices append "document" and "invoice" with no schema change.
EntityType = Literal["customer", "person", "deal"]

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify_key(raw: str) -> str:
    return _SLUG_STRIP.sub("_", raw.strip().lower()).strip("_")


class FieldDefinitionCreate(BaseModel):
    entity_type: EntityType
    key: str
    label: str
    field_type: FieldType
    options: list[str] = []
    required: bool = False
    position: int = 0

    @field_validator("key", mode="before")
    @classmethod
    def _slugify(cls, value: str) -> str:
        return slugify_key(value)


class FieldDefinitionUpdate(BaseModel):
    """`field_type` is deliberately absent. Changing it with existing values has no
    correct answer, so the operation does not exist at any layer."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    options: list[str] | None = None
    required: bool | None = None
    position: int | None = None


class FieldDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: EntityType
    key: str
    label: str
    field_type: FieldType
    options: list[str]
    required: bool
    position: int
    archived: bool
