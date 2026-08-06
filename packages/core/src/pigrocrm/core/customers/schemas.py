from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Mirror Customer's column widths (models.py). Without these, an over-length value
# sails past Pydantic, reaches flush(), and comes back as a raw sqlalchemy.exc.DataError
# (StringDataRightTruncation) -- not a subclass of IntegrityError, so no handler catches
# it, and it poisons the session. The same gap fields/schemas.py's KEY_MAX_LENGTH and
# pipeline/schemas.py's NOME_MAX_LENGTH/CODE_MAX_LENGTH already close; this is the
# fourth time this project has hit it.
#
# `partita_iva` is deliberately absent from this list -- see the comment on
# `CustomerCreate.partita_iva` below for why bounding it here would be actively wrong,
# not merely redundant.
RAGIONE_SOCIALE_MAX_LENGTH = 255
CODICE_FISCALE_MAX_LENGTH = 16
CODICE_SDI_MAX_LENGTH = 7
PEC_MAX_LENGTH = 320
INDIRIZZO_MAX_LENGTH = 255
CAP_MAX_LENGTH = 10
COMUNE_MAX_LENGTH = 120
PROVINCIA_MAX_LENGTH = 2
NAZIONE_MAX_LENGTH = 2
EMAIL_MAX_LENGTH = 320
TELEFONO_MAX_LENGTH = 40
SITO_WEB_MAX_LENGTH = 255
STATO_MAX_LENGTH = 40


class CustomerCreate(BaseModel):
    ragione_sociale: str = Field(max_length=RAGIONE_SOCIALE_MAX_LENGTH)
    # No `max_length` here, unlike every other fiscal field below: the service's
    # `_check_fiscal` already requires an exact `^\d{11}$` match on every create and
    # update, which structurally rejects any value whose length is not 11 -- a stricter
    # condition than `max_length=11` alone, which would accept a too-short digit string
    # a Pydantic bound cannot distinguish from a valid one. Adding `max_length=11` here
    # as well would not close any additional gap; it would instead intercept an
    # over-length value *before* `_check_fiscal` runs and raise pydantic's own
    # `ValidationError` instead of this project's `ValidationFailed` -- a regression a
    # 12-digit input must not trigger.
    partita_iva: str | None = None
    codice_fiscale: str | None = Field(default=None, max_length=CODICE_FISCALE_MAX_LENGTH)
    # No `max_length` either, for the same reason as `partita_iva`: `_check_fiscal`
    # already requires exactly 7 characters on every create and update.
    codice_sdi: str | None = None
    pec: str | None = Field(default=None, max_length=PEC_MAX_LENGTH)
    indirizzo: str | None = Field(default=None, max_length=INDIRIZZO_MAX_LENGTH)
    cap: str | None = Field(default=None, max_length=CAP_MAX_LENGTH)
    comune: str | None = Field(default=None, max_length=COMUNE_MAX_LENGTH)
    provincia: str | None = Field(default=None, max_length=PROVINCIA_MAX_LENGTH)
    nazione: str = Field(default="IT", max_length=NAZIONE_MAX_LENGTH)
    email: str | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    telefono: str | None = Field(default=None, max_length=TELEFONO_MAX_LENGTH)
    sito_web: str | None = Field(default=None, max_length=SITO_WEB_MAX_LENGTH)
    stato: str | None = Field(default=None, max_length=STATO_MAX_LENGTH)
    note: str | None = None
    custom_fields: dict[str, Any] = {}


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ragione_sociale: str | None = Field(default=None, max_length=RAGIONE_SOCIALE_MAX_LENGTH)
    # See CustomerCreate.partita_iva: _check_fiscal covers this field's length exactly,
    # so no Pydantic bound is added here either.
    partita_iva: str | None = None
    codice_fiscale: str | None = Field(default=None, max_length=CODICE_FISCALE_MAX_LENGTH)
    # See CustomerCreate.codice_sdi: _check_fiscal covers this field's length exactly.
    codice_sdi: str | None = None
    pec: str | None = Field(default=None, max_length=PEC_MAX_LENGTH)
    indirizzo: str | None = Field(default=None, max_length=INDIRIZZO_MAX_LENGTH)
    cap: str | None = Field(default=None, max_length=CAP_MAX_LENGTH)
    comune: str | None = Field(default=None, max_length=COMUNE_MAX_LENGTH)
    provincia: str | None = Field(default=None, max_length=PROVINCIA_MAX_LENGTH)
    nazione: str | None = Field(default=None, max_length=NAZIONE_MAX_LENGTH)
    email: str | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    telefono: str | None = Field(default=None, max_length=TELEFONO_MAX_LENGTH)
    sito_web: str | None = Field(default=None, max_length=SITO_WEB_MAX_LENGTH)
    stato: str | None = Field(default=None, max_length=STATO_MAX_LENGTH)
    note: str | None = None
    custom_fields: dict[str, Any] | None = None


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ragione_sociale: str
    partita_iva: str | None
    codice_fiscale: str | None
    codice_sdi: str | None
    pec: str | None
    indirizzo: str | None
    cap: str | None
    comune: str | None
    provincia: str | None
    nazione: str
    email: str | None
    telefono: str | None
    sito_web: str | None
    stato: str | None
    note: str | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CustomerListQuery(BaseModel):
    search: str | None = None
    stato: str | None = None
    custom: dict[str, Any] | None = None
    limit: int = 50
    cursor: UUID | None = None


class CustomerPage(BaseModel):
    items: list[CustomerRead]
    next_cursor: UUID | None
