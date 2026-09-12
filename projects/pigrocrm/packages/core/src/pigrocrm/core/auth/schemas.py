from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from pigrocrm.core.actor import Role
from pigrocrm.core.validation import SafeStr

MIN_PASSWORD_LENGTH = 10

# `tariffa_oraria_default`/`costo_orario_default` are Numeric(12,6) -- factors, not
# amounts. Declared locally rather than imported from `deals/schemas.py`: `deals`
# and `auth` do not depend on each other today and this is not the reason to start.
FACTOR_MAX_DIGITS = 12
FACTOR_DECIMAL_PLACES = 6

# Mirrors `users.nome`'s column width (auth/models.py: String(200)). Predates every
# other domain's *_MAX_LENGTH sweep and was never itself swept until the final
# review: without this, an over-length value sails past Pydantic, reaches flush(),
# and comes back as a raw sqlalchemy.exc.DataError (StringDataRightTruncation) --
# not a subclass of IntegrityError, so no handler catches it, and it poisons the
# session. `email` needs no equivalent bound: it is `EmailStr`, and email-validator
# already refuses an address longer than RFC 5321's own limit (~254 characters),
# comfortably under this column's `String(320)` -- verified directly against the
# installed email-validator, not assumed. `password` is never stored: only its
# argon2 hash is, in a column of its own, so no column width applies to it here at
# all.
NOME_MAX_LENGTH = 200


class UserCreate(BaseModel):
    email: EmailStr
    # `None` only for a space's first admin, created by the signup wizard (spec
    # 2026-09-12 §6.4): the person enters with a link by mail and never had a password.
    # `UserService.create` refuses it from anyone but the system.
    password: str | None = None
    nome: SafeStr = Field(max_length=NOME_MAX_LENGTH)
    ruolo: Role = "collaboratore"
    tariffa_oraria_default: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_DECIMAL_PLACES, ge=0
    )
    costo_orario_default: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_DECIMAL_PLACES, ge=0
    )

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class UserUpdate(BaseModel):
    nome: SafeStr | None = Field(default=None, max_length=NOME_MAX_LENGTH)
    ruolo: Role | None = None
    attivo: bool | None = None
    tariffa_oraria_default: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_DECIMAL_PLACES, ge=0
    )
    costo_orario_default: Decimal | None = Field(
        default=None, max_digits=FACTOR_MAX_DIGITS, decimal_places=FACTOR_DECIMAL_PLACES, ge=0
    )


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    nome: str
    ruolo: Role
    attivo: bool
    tariffa_oraria_default: Decimal | None
    costo_orario_default: Decimal | None
    created_at: datetime
