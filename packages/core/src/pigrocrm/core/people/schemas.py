from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pigrocrm.core.validation import SafeStr

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
    nome: SafeStr = Field(max_length=NOME_MAX_LENGTH)
    cognome: SafeStr | None = Field(default=None, max_length=COGNOME_MAX_LENGTH)
    # Plain `str`, not `EmailStr`: format is checked separately by the service's own
    # `_check_email` regex below, not by the schema. `SafeStr` closes the NUL-byte gap
    # that regex does not: `[^@\s]` matches a NUL byte just as readily as a letter.
    email: SafeStr | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    telefono: SafeStr | None = Field(default=None, max_length=TELEFONO_MAX_LENGTH)
    ruolo: SafeStr | None = Field(default=None, max_length=RUOLO_MAX_LENGTH)
    linkedin: SafeStr | None = Field(default=None, max_length=LINKEDIN_MAX_LENGTH)
    note: SafeStr | None = None
    customer_id: UUID | None = None
    custom_fields: dict[str, Any] = {}

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        # `mode="before"` runs ahead of both the `max_length` constraint above and
        # SafeStr's own NUL check -- like `FieldDefinitionCreate.key`'s slugify
        # validator (fields/schemas.py) -- so both apply to the normalised value, not
        # to whatever raw string arrived. Stripping/lowering never removes a NUL byte,
        # so SafeStr still catches one introduced anywhere in the original input.
        return _normalise_email(value)


class PersonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: SafeStr | None = Field(default=None, max_length=NOME_MAX_LENGTH)
    cognome: SafeStr | None = Field(default=None, max_length=COGNOME_MAX_LENGTH)
    email: SafeStr | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    telefono: SafeStr | None = Field(default=None, max_length=TELEFONO_MAX_LENGTH)
    ruolo: SafeStr | None = Field(default=None, max_length=RUOLO_MAX_LENGTH)
    linkedin: SafeStr | None = Field(default=None, max_length=LINKEDIN_MAX_LENGTH)
    note: SafeStr | None = None
    customer_id: UUID | None = None
    custom_fields: dict[str, Any] | None = None
    # Detaching is its own explicit flag rather than an overloaded `customer_id=None`.
    # It was born as a workaround -- `exclude_none` could not express "set customer_id
    # back to null" -- and task 4B-1, which closed A14, could have retired it. It did
    # not: `detach` is already the shape every caller and the MCP schema below are
    # written against, and it names an intention ("unlink this person") that a bare
    # `null` does not. `PersonService.update` keeps `customer_id` out of the generic
    # dump for the same reason, so the two spellings cannot disagree.
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
