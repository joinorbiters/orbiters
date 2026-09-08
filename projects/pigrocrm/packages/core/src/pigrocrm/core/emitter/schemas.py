from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pigrocrm.core.validation import SafeStr

# Mirror EmitterProfile's column widths exactly (emitter/models.py). Without these an
# over-long value reaches Postgres and raises sqlalchemy.exc.DataError, which is not
# an IntegrityError subclass, so no handler catches it and the session is poisoned.
RAGIONE_SOCIALE_MAX_LENGTH = 255
CODICE_FISCALE_MAX_LENGTH = 16
INDIRIZZO_MAX_LENGTH = 255
CAP_MAX_LENGTH = 10
COMUNE_MAX_LENGTH = 120
PROVINCIA_MAX_LENGTH = 2
NAZIONE_MAX_LENGTH = 2
PEC_MAX_LENGTH = 320
TELEFONO_MAX_LENGTH = 40
EMAIL_MAX_LENGTH = 320
SITO_WEB_MAX_LENGTH = 255
STORAGE_KEY_MAX_LENGTH = 255
REGIME_FISCALE_MAX_LENGTH = 200
# `firma_email` is a `Text` column, so it has no width for this to mirror and nothing
# above breaks if it is exceeded. Bounded anyway, on `templates/schemas.py`'s own
# reasoning about a string nested in JSONB: an unbounded text field on a signature
# block is still an unbounded text field, and a signature has no more use for 100 000
# characters than a template variable name does.
FIRMA_EMAIL_MAX_LENGTH = 2_000


class EmitterProfileUpsert(BaseModel):
    """One shape for create and update: there is only ever one row, so "create" and
    "update" are the same operation with the same required fields.

    `partita_iva` and `codice_sdi` carry no `max_length`, exactly as
    `CustomerCreate` does: the service's `_check_fiscal` already requires an exact
    11-digit / 7-character match, which is stricter, and adding a Pydantic bound would
    make a 12-digit input raise pydantic's own `ValidationError` instead of this
    project's `ValidationFailed` -- a regression, not a fix.
    """

    model_config = ConfigDict(extra="forbid")

    ragione_sociale: SafeStr = Field(max_length=RAGIONE_SOCIALE_MAX_LENGTH)
    partita_iva: SafeStr | None = None
    codice_fiscale: SafeStr | None = Field(default=None, max_length=CODICE_FISCALE_MAX_LENGTH)
    indirizzo: SafeStr | None = Field(default=None, max_length=INDIRIZZO_MAX_LENGTH)
    cap: SafeStr | None = Field(default=None, max_length=CAP_MAX_LENGTH)
    comune: SafeStr | None = Field(default=None, max_length=COMUNE_MAX_LENGTH)
    provincia: SafeStr | None = Field(default=None, max_length=PROVINCIA_MAX_LENGTH)
    nazione: SafeStr = Field(default="IT", max_length=NAZIONE_MAX_LENGTH)
    pec: SafeStr | None = Field(default=None, max_length=PEC_MAX_LENGTH)
    codice_sdi: SafeStr | None = None
    telefono: SafeStr | None = Field(default=None, max_length=TELEFONO_MAX_LENGTH)
    email: SafeStr | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    sito_web: SafeStr | None = Field(default=None, max_length=SITO_WEB_MAX_LENGTH)
    logo_key: SafeStr | None = Field(default=None, max_length=STORAGE_KEY_MAX_LENGTH)
    firma_key: SafeStr | None = Field(default=None, max_length=STORAGE_KEY_MAX_LENGTH)
    firma_email: SafeStr | None = Field(default=None, max_length=FIRMA_EMAIL_MAX_LENGTH)
    regime_fiscale: SafeStr | None = Field(default=None, max_length=REGIME_FISCALE_MAX_LENGTH)


class EmitterProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ragione_sociale: str
    partita_iva: str | None
    codice_fiscale: str | None
    indirizzo: str | None
    cap: str | None
    comune: str | None
    provincia: str | None
    nazione: str
    pec: str | None
    codice_sdi: str | None
    telefono: str | None
    email: str | None
    sito_web: str | None
    logo_key: str | None
    firma_key: str | None
    firma_email: str | None
    regime_fiscale: str | None
    created_at: datetime
    updated_at: datetime
