from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Mirror Person's column widths (models.py). Without these, an over-length value
# sails past Pydantic, reaches flush(), and comes back as a raw sqlalchemy.exc.DataError
# (StringDataRightTruncation) -- not a subclass of IntegrityError, so no handler catches
# it, and it poisons the session. The same gap CustomerCreate's own *_MAX_LENGTH
# constants close on Customer (customers/schemas.py); this project has hit the class of
# bug often enough that it is now a standing global constraint, not a one-off fix.
#
# `note` is deliberately absent: it is `Text` in models.py, which has no column width to
# mirror.
NOME_MAX_LENGTH = 120
COGNOME_MAX_LENGTH = 120
EMAIL_MAX_LENGTH = 320
TELEFONO_MAX_LENGTH = 40
RUOLO_MAX_LENGTH = 120
LINKEDIN_MAX_LENGTH = 255


def _normalise_email(value: str | None) -> str | None:
    return value.strip().lower() if isinstance(value, str) else value


class PersonCreate(BaseModel):
    nome: str = Field(max_length=NOME_MAX_LENGTH)
    cognome: str | None = Field(default=None, max_length=COGNOME_MAX_LENGTH)
    email: str | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    telefono: str | None = Field(default=None, max_length=TELEFONO_MAX_LENGTH)
    ruolo: str | None = Field(default=None, max_length=RUOLO_MAX_LENGTH)
    linkedin: str | None = Field(default=None, max_length=LINKEDIN_MAX_LENGTH)
    note: str | None = None
    customer_id: UUID | None = None
    custom_fields: dict[str, Any] = {}

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        # `mode="before"` runs ahead of the `max_length` constraint above -- like
        # `FieldDefinitionCreate.key`'s slugify validator (fields/schemas.py) -- so the
        # bound applies to the normalised value, not to whatever raw string arrived.
        return _normalise_email(value)


class PersonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = Field(default=None, max_length=NOME_MAX_LENGTH)
    cognome: str | None = Field(default=None, max_length=COGNOME_MAX_LENGTH)
    email: str | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    telefono: str | None = Field(default=None, max_length=TELEFONO_MAX_LENGTH)
    ruolo: str | None = Field(default=None, max_length=RUOLO_MAX_LENGTH)
    linkedin: str | None = Field(default=None, max_length=LINKEDIN_MAX_LENGTH)
    note: str | None = None
    customer_id: UUID | None = None
    custom_fields: dict[str, Any] | None = None
    # `exclude_none` on a partial update cannot express "set customer_id back to
    # null" -- None already means "leave this field alone" for every other field
    # here -- so detaching is its own explicit flag instead of overloading
    # customer_id=None.
    #
    # The `description` is not decorative: this field's own JSON Schema entry is
    # what an MCP client renders for `changes.detach` (see apps/mcp's
    # `PersonChanges` schema override), and the bare name "detach" does not say
    # what it detaches -- unlike `customer_id`, which reads as what it is.
    detach: bool = Field(
        default=False,
        description=(
            "Se true, rimuove il collegamento della persona al cliente attuale invece di "
            "assegnarne uno nuovo con customer_id."
        ),
    )

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return _normalise_email(value)


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    cognome: str | None
    email: str | None
    telefono: str | None
    ruolo: str | None
    linkedin: str | None
    note: str | None
    customer_id: UUID | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PersonListQuery(BaseModel):
    search: str | None = None
    customer_id: UUID | None = None
    custom: dict[str, Any] | None = None
    # Upper-bounded so a caller (an MCP agent especially) cannot request an
    # unbounded page; matches CustomerListQuery.limit exactly.
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class PersonPage(BaseModel):
    items: list[PersonRead]
    next_cursor: UUID | None
