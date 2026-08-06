from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from pigrocrm.core.actor import Role

MIN_PASSWORD_LENGTH = 10


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    nome: str
    ruolo: Role = "collaboratore"

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class UserUpdate(BaseModel):
    nome: str | None = None
    ruolo: Role | None = None
    attivo: bool | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    nome: str
    ruolo: Role
    attivo: bool
    created_at: datetime
