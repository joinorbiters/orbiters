from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class SignupCreate(BaseModel):
    # `EmailStr` already refuses anything past RFC 5321's ~254 characters, well under
    # the column's String(320) -- the same reasoning `auth/schemas.py` records.
    email: EmailStr


class SignupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    created_at: datetime
    # `True` the first time an address is seen, `False` when it was already there. The
    # page says "sei in orbita" either way; the flag is for whoever reads the API.
    nuova: bool
