from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from orbiters_core.models import (
    AZIENDA_MAX_LENGTH,
    DURATA_MAX_LENGTH,
    LINKEDIN_URL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    POSIZIONE_MAX_LENGTH,
    UTM_MAX_LENGTH,
)
from orbiters_core.validation import SafeStr

LINKEDIN_HOST = "linkedin.com"
# What the landing sends in `oppref`, bounded to the same 512 characters it bounds it to
# (`orbiters.js`'s `OPPREF_MAX_LENGTH`). Not a column width: nothing stores this.
OPPREF_MAX_LENGTH = 512

# Characters that must never reach a stored value. C0 (tab, CR, LF included), DEL and
# C1 are refused because `urllib.parse` strips tab/CR/LF from a URL *before* parsing
# it, so a value with a newline in it validated as a URL and was then stored whole --
# `.../in/ada\nBcc: qualcuno@altrove.it` was accepted. The same string is later read by
# an assistant drafting mail to these people, which is where a newline stops being
# cosmetic. The bidi controls are refused for the mirror-image reason: they make a
# stored name render as a different name, so what an admin reads is not what is there.
BIDI_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _reject_control_characters(value: str) -> str:
    """Refuses rather than strips, and looks at the value *before* it is trimmed or
    parsed, so nothing invisible is deleted on the way to the column -- the reasoning
    `validation.py` records for `SafeStr`, which closes only `\x00`. Note that Python's
    own `str.strip()` treats `\n`, `\t` and even `\x85` as whitespace, so checking
    after trimming would let a trailing control character disappear in silence."""
    for character in value:
        if character < " " or character == "\x7f" or "\x80" <= character <= "\x9f":
            raise ValueError("il testo contiene un carattere di controllo, non ammesso")
        if character in BIDI_CONTROLS:
            raise ValueError("il testo contiene un carattere di direzione, non ammesso")
    return value


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
    # A key this form does not have is a 422, not a value quietly dropped: a landing
    # served from a stale cache posts the body from before nome and cognome existed,
    # and pydantic's default `extra="ignore"` would store that signup without the two
    # fields this form exists to collect, with nothing anywhere saying so.
    model_config = ConfigDict(extra="forbid")

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
    # The two values below are for the conversion event and are **never stored**: no
    # column, no migration, nothing in `SignupListItem`. They travel in this body only
    # because the landing is where both are known, and because `extra="forbid"` above
    # means a key the schema does not declare is a 422 -- so an undeclared field is not
    # an option, and a stored one would be data nobody asked to keep.
    #
    # `pixel_event_id` is the id the landing generated for this submitted form and also
    # passed to `oaiq("measure", ...)`. Deduplication is on (pixel id, event name, id),
    # so the two halves of one conversion are one conversion only if this reaches the
    # server unchanged. Constrained to what an id may be: it is interpolated into a JSON
    # body sent to a third party, and there is no reason for it to contain anything else.
    pixel_event_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{8,64}$")
    # OpenAI's own click identifier, from the landing URL. "Pass unchanged" is their
    # instruction, so it is bounded and checked for control characters and nothing more:
    # its shape is theirs to change, and a value we do not recognise is still the value
    # that arrived.
    oppref: SafeStr | None = Field(default=None, max_length=OPPREF_MAX_LENGTH)

    @field_validator("oppref", mode="after")
    @classmethod
    def _oppref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = _reject_control_characters(value).strip()
        return trimmed or None

    @field_validator("nome", "cognome", mode="after")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        """Trimmed here rather than in the landing's JavaScript alone: the API is the
        one public write in the CRM, and `"  "` must not become a name of two spaces."""
        trimmed = _reject_control_characters(value).strip()
        if not trimmed:
            raise ValueError("serve un valore, non solo spazi")
        return trimmed

    @field_validator("linkedin_url", mode="after")
    @classmethod
    def _linkedin(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        # Checked, then normalised, then stored -- and what was checked is what is
        # stored: `urllib.parse` strips tab, CR and LF from a URL before parsing it, so
        # the old order validated one string and wrote another.
        trimmed = _reject_control_characters(value).strip()
        parts = urlsplit(trimmed)
        host = (parts.hostname or "").lower()
        # `https` only, so the landing's own check and this one agree, and so the stored
        # value is always a link worth following. The host is compared, never searched:
        # `https://evil.com/linkedin.com/x` and `https://linkedin.com.evil.com/` are not
        # profiles, and `urlsplit` is what decides which part of the string is the host.
        if parts.scheme != "https" or not (
            host == LINKEDIN_HOST or host.endswith(f".{LINKEDIN_HOST}")
        ):
            raise ValueError(
                f"serve l'indirizzo https di un profilo su {LINKEDIN_HOST}, oppure niente"
            )
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
    """The outcome of `SignupService.subscribe`, for its caller inside the process.

    Deliberately carries nothing that was *already* in the row. It used to echo the
    stored `nome`, `cognome`, `linkedin_url` and `utm_*`, and since a repeated signup
    returns the existing row rather than the submitted values, that made the one
    unauthenticated write in the API an oracle: post somebody else's address with any
    name and the answer handed back their real name and LinkedIn profile. The whole row
    is `SignupListItem`, and the only way to it is admin-gated (`list_recent`).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    created_at: datetime
    # `True` the first time an address is seen, `False` when it was already there. Never
    # leaves the process: the router answers `SignupAck`, which does not say which.
    nuova: bool = False


class SignupAck(BaseModel):
    """What the public POST answers, and all it answers: the request was accepted.

    The same body and the same 201 for a first signup and for the hundredth, so the
    reply does not say whether the address was already on the list either. The landing
    needs nothing more -- it branches on the status alone -- and anything more would be
    readable by anyone who can guess an email address.
    """

    ok: bool = True


# ---- the hub proper -------------------------------------------------------------------

Remoto = Literal["remoto", "ibrido", "in_sede"]
FreelancerStato = Literal["nuovo", "contattato", "attivo", "scartato"]
CompanyStato = Literal["nuovo", "contattato", "in_corso", "chiuso"]

# A day's worth of work, in euro. Wide enough for anyone, narrow enough that a typo of
# one extra zero is still a number the admin can read and correct.
TARIFFA_MIN = Decimal("1")
TARIFFA_MAX = Decimal("99999.99")
LINKS_MAX = 10
LINK_MAX_LENGTH = 300
PROGETTO_MAX_LENGTH = 4000


def _clean_text(value: str, *, what: str) -> str:
    trimmed = _reject_control_characters(value).strip()
    if not trimmed:
        raise ValueError(f"serve {what}, non solo spazi")
    return trimmed


def _https_url(value: str) -> str:
    """Any https address: the additional links are the person's own (a site, a GitHub,
    a portfolio), so the host is not checked, only that it is a link worth following."""
    trimmed = _reject_control_characters(value).strip()
    parts = urlsplit(trimmed)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("serve un indirizzo https completo")
    return trimmed


class FreelancerCreate(BaseModel):
    """What the wizard collects. The CV travels beside this body, not inside it: the API
    takes it as a multipart file and hands the bytes to the service with this schema."""

    model_config = ConfigDict(extra="forbid")

    nome: SafeStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    cognome: SafeStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    email: EmailStr
    linkedin_url: SafeStr | None = Field(default=None, max_length=LINKEDIN_URL_MAX_LENGTH)
    tariffa_giornaliera: Decimal = Field(
        max_digits=7, decimal_places=2, ge=TARIFFA_MIN, le=TARIFFA_MAX
    )
    posizione: SafeStr = Field(min_length=1, max_length=POSIZIONE_MAX_LENGTH)
    remoto: Remoto
    links: list[SafeStr] = Field(default_factory=list, max_length=LINKS_MAX)
    utm: SignupUtm | None = None

    @field_validator("nome", "cognome", "posizione", mode="after")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        return _clean_text(value, what="un valore")

    @field_validator("linkedin_url", mode="after")
    @classmethod
    def _linkedin(cls, value: str | None) -> str | None:
        return SignupCreate._linkedin(value)

    @field_validator("links", mode="after")
    @classmethod
    def _links(cls, value: list[str]) -> list[str]:
        cleaned = [_https_url(link) for link in value if link.strip()]
        if any(len(link) > LINK_MAX_LENGTH for link in cleaned):
            raise ValueError(f"un link può avere al massimo {LINK_MAX_LENGTH} caratteri")
        return cleaned


class CompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome_azienda: SafeStr = Field(min_length=1, max_length=AZIENDA_MAX_LENGTH)
    referente: SafeStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    email: EmailStr
    progetto: SafeStr = Field(min_length=1, max_length=PROGETTO_MAX_LENGTH)
    periodo_da: date
    durata: SafeStr = Field(min_length=1, max_length=DURATA_MAX_LENGTH)
    budget_giornaliero: Decimal = Field(
        max_digits=7, decimal_places=2, ge=TARIFFA_MIN, le=TARIFFA_MAX
    )
    utm: SignupUtm | None = None

    @field_validator("nome_azienda", "referente", "durata", mode="after")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        return _clean_text(value, what="un valore")

    @field_validator("progetto", mode="after")
    @classmethod
    def _progetto(cls, value: str) -> str:
        """Multi-line is the point of a project description, so newlines stay; every
        other control character and the bidi overrides are refused as everywhere else."""
        for character in value:
            if character in "\n\r\t":
                continue
            _reject_control_characters(character)
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("serve una descrizione del progetto, non solo spazi")
        return trimmed


class Ack(BaseModel):
    """What every public POST of the hub answers, and all it answers: accepted."""

    ok: bool = True


class FreelancerRead(BaseModel):
    """The row as an admin reads it. Never the CV bytes: those have their own download,
    so a list of two hundred people is not two hundred PDFs in one response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    cognome: str
    email: str
    linkedin_url: str | None
    cv_filename: str
    cv_mime: str
    cv_size: int
    tariffa_giornaliera: Decimal
    posizione: str
    remoto: str
    links: list[str]
    stato: str
    note: str | None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    utm_id: str | None = None
    created_at: datetime
    updated_at: datetime


class FreelancerList(BaseModel):
    totale: int
    items: list[FreelancerRead]


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome_azienda: str
    referente: str
    email: str
    progetto: str
    periodo_da: date
    durata: str
    budget_giornaliero: Decimal
    stato: str
    note: str | None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    utm_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CompanyList(BaseModel):
    totale: int
    items: list[CompanyRead]


class StatusChange(BaseModel):
    """What an admin changes on a row: where it stands, and a note to themselves."""

    stato: str = Field(min_length=1, max_length=20)
    note: SafeStr | None = Field(default=None, max_length=PROGETTO_MAX_LENGTH)


class CvFile(BaseModel):
    """The bytes and the two headers a download needs."""

    filename: str
    mime: str
    content: bytes
