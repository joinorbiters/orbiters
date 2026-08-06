import re
import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pigrocrm.core.fields.types import FieldType

# Open by design: later slices append "document" and "invoice" with no schema change.
EntityType = Literal["customer", "person", "deal"]

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Mirrors the width of the `key` / `label` columns in fields/models.py. Without this,
# an over-length value sails past Pydantic, reaches `flush()`, and comes back as a raw
# sqlalchemy.exc.DataError (StringDataRightTruncation) -- which is not a subclass of
# IntegrityError, so the service's `except IntegrityError` around the commit does not
# catch it. Bounding it here turns that into an ordinary pydantic ValidationError
# before the request ever reaches the service.
KEY_MAX_LENGTH = 60
LABEL_MAX_LENGTH = 120


def slugify_key(raw: str) -> str:
    """Lossless-where-possible: an accented letter becomes its plain-ASCII base
    letter ("città" -> "citta"), not silence. NFKD decomposes each accented character
    into a base letter plus a separate combining mark; dropping only the combining
    marks keeps the letter. A character with no ASCII base at all (e.g. CJK) is still
    discarded -- there is no letter to fall back to -- and input that is only
    punctuation or only such characters slugifies to "", which the service rejects."""
    decomposed = unicodedata.normalize("NFKD", raw)
    transliterated = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SLUG_STRIP.sub("_", transliterated.strip().lower()).strip("_")


class FieldDefinitionCreate(BaseModel):
    entity_type: EntityType
    key: str = Field(max_length=KEY_MAX_LENGTH)
    label: str = Field(max_length=LABEL_MAX_LENGTH)
    field_type: FieldType
    options: list[str] = []
    required: bool = False
    position: int = 0

    @field_validator("key", mode="before")
    @classmethod
    def _slugify(cls, value: str) -> str:
        # A `mode="before"` validator runs before Pydantic's own field constraints
        # (here, `max_length`), so the bound below applies to the slugified key, not
        # to whatever raw string the caller sent.
        return slugify_key(value)


class FieldDefinitionUpdate(BaseModel):
    """`field_type` is deliberately absent. Changing it with existing values has no
    correct answer, so the operation does not exist at any layer."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=LABEL_MAX_LENGTH)
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
