from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from pigrocrm.core.orbiters.models import (
    LINKEDIN_URL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    UTM_MAX_LENGTH,
)
from pigrocrm.core.validation import SafeStr

LINKEDIN_HOST = "linkedin.com"


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
    # Required here even though the columns are nullable: the nulls belong to the rows
    # collected before the form asked, and nothing new is allowed to add one. Bounded to
    # the column, and `SafeStr` closes the NUL-byte gap a plain `str` would leave open.
    nome: SafeStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    cognome: SafeStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    # A profile, not any URL: the scheme has to be http(s) and the host has to be
    # LinkedIn's, so a typo or somebody else's site is a 422 and never a stored link
    # nobody can use. Kept exactly as it was typed -- no trailing slash added, no
    # normalisation -- because it is a person's own address for themselves.
    linkedin_url: SafeStr | None = Field(default=None, max_length=LINKEDIN_URL_MAX_LENGTH)
    utm: SignupUtm | None = None

    @field_validator("nome", "cognome", mode="after")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        """Trimmed here rather than in the landing's JavaScript alone: the API is the
        one public write in the CRM, and `"  "` must not become a name of two spaces."""
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("serve un valore, non solo spazi")
        return trimmed

    @field_validator("linkedin_url", mode="after")
    @classmethod
    def _linkedin(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        trimmed = value.strip()
        parts = urlsplit(trimmed)
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or not (
            host == LINKEDIN_HOST or host.endswith(f".{LINKEDIN_HOST}")
        ):
            raise ValueError(f"serve l'indirizzo di un profilo su {LINKEDIN_HOST}, oppure niente")
        return trimmed


class SignupListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    created_at: datetime
    # `None` only for the rows written before the form asked for a name.
    nome: str | None = None
    cognome: str | None = None
    linkedin_url: str | None = None
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
    nome: str | None = None
    cognome: str | None = None
    linkedin_url: str | None = None
    # `True` the first time an address is seen, `False` when it was already there. The
    # page says "sei in orbita" either way; the flag is for whoever reads the API.
    nuova: bool = False
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    utm_id: str | None = None
