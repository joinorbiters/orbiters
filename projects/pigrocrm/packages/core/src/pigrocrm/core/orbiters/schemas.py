from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from pigrocrm.core.orbiters.models import UTM_MAX_LENGTH


class SignupUtm(BaseModel):
    """The attribution the landing read from its own URL, if any. Every key optional and
    bounded: an ad platform's macro left unexpanded (`{{AD_SET_ID}}`) is stored as the
    literal it arrived as, because that is what happened."""

    utm_source: str | None = Field(default=None, max_length=UTM_MAX_LENGTH)
    utm_medium: str | None = Field(default=None, max_length=UTM_MAX_LENGTH)
    utm_campaign: str | None = Field(default=None, max_length=UTM_MAX_LENGTH)
    utm_content: str | None = Field(default=None, max_length=UTM_MAX_LENGTH)
    utm_term: str | None = Field(default=None, max_length=UTM_MAX_LENGTH)
    utm_id: str | None = Field(default=None, max_length=UTM_MAX_LENGTH)

    def is_empty(self) -> bool:
        return not any(self.model_dump().values())


class SignupCreate(BaseModel):
    # `EmailStr` already refuses anything past RFC 5321's ~254 characters, well under
    # the column's String(320) -- the same reasoning `auth/schemas.py` records.
    email: EmailStr
    utm: SignupUtm | None = None


class SignupListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    created_at: datetime
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    utm_id: str | None = None


class SignupList(BaseModel):
    """Newest first. `totale` counts the whole list, not just the page returned."""

    totale: int
    iscrizioni: list[SignupListItem]


class SignupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    created_at: datetime
    # `True` the first time an address is seen, `False` when it was already there. The
    # page says "sei in orbita" either way; the flag is for whoever reads the API.
    nuova: bool = False
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    utm_id: str | None = None
