from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, LargeBinary, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from orbiters_core.db import Base, PrimaryKeyMixin, TimestampMixin

UTM_MAX_LENGTH = 200
UTM_COLUMNS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "utm_id")
NAME_MAX_LENGTH = 120
LINKEDIN_URL_MAX_LENGTH = 300

# Every column added after the production table already existed, with the width each
# one needs. Migration 0001 adopts that table as it stands and adds these with
# `ADD COLUMN IF NOT EXISTS`, which is how the rows PigroCRM's sidecar collected keep
# their place. The UTM six arrived on 2026-09-08, `nome`/`cognome`/`linkedin_url` right
# after; the tuple stays because `test_migrations.py` proves the adoption against a
# table that predates all of them.
LATE_COLUMNS: tuple[tuple[str, int], ...] = (
    *((column, UTM_MAX_LENGTH) for column in UTM_COLUMNS),
    ("nome", NAME_MAX_LENGTH),
    ("cognome", NAME_MAX_LENGTH),
    ("linkedin_url", LINKEDIN_URL_MAX_LENGTH),
)


class Signup(Base, PrimaryKeyMixin):
    __tablename__ = "signups"

    # Same width and the same case-insensitive uniqueness as `users.email`: the
    # service lowers the address before writing, and the functional index is what
    # makes that a database fact rather than an app-level habit.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Where the signup came from, as the URL said it: the five standard UTM keys plus
    # `utm_id`, which LinkedIn fills with the ad set. All optional, all written once --
    # the first attribution of an address is the one that stays (see `SignupService`).
    # Added to a table that already existed in production: migration 0001 adds them.
    utm_source: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_medium: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_campaign: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_content: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_term: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_id: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    # Who they are. `SignupCreate` requires both, so nothing written from today on is
    # nameless -- but the twenty-four rows the form collected when it asked only for an
    # address have no name to give, so the columns stay nullable rather than being
    # backfilled with `''`, which would claim a name was recorded and found empty.
    # An empty column is filled in the next time that address signs up (`SignupService`).
    nome: Mapped[str | None] = mapped_column(String(NAME_MAX_LENGTH), default=None)
    cognome: Mapped[str | None] = mapped_column(String(NAME_MAX_LENGTH), default=None)
    # Optional for everyone, always: a freelance with no LinkedIn is still a freelance.
    linkedin_url: Mapped[str | None] = mapped_column(String(LINKEDIN_URL_MAX_LENGTH), default=None)

    __table_args__ = (Index("uq_orbiters_signups_email_lower", func.lower(email), unique=True),)


# ---- the hub proper: who wants to work, and who needs people --------------------------

FREELANCER_STATES = ("nuovo", "contattato", "attivo", "scartato")
COMPANY_STATES = ("nuovo", "contattato", "in_corso", "chiuso")
REMOTE_OPTIONS = ("remoto", "ibrido", "in_sede")
POSIZIONE_MAX_LENGTH = 160
AZIENDA_MAX_LENGTH = 200
DURATA_MAX_LENGTH = 120
CV_FILENAME_MAX_LENGTH = 255
CV_MIME_MAX_LENGTH = 100
# Five megabytes: a CV is two pages, and the largest a designer's portfolio-as-CV gets
# before it stops being a CV. Enforced in the service on the bytes themselves, so the
# API and the MCP server cannot disagree about it.
CV_MAX_BYTES = 5 * 1024 * 1024


class UtmMixin:
    """Where a submission came from, as the page's URL said it. Optional, written once."""

    utm_source: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_medium: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_campaign: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_content: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_term: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)
    utm_id: Mapped[str | None] = mapped_column(String(UTM_MAX_LENGTH), default=None)


class Freelancer(Base, PrimaryKeyMixin, TimestampMixin, UtmMixin):
    """A person who filled in the hub's wizard: who they are, what they do, what they
    cost, and their CV -- in the row, as bytes. In the database rather than on a disk or
    a Drive because a CV is personal data with a retention to honour, and one place to
    delete from is one place (hub spec, 2026-09-09; Ivan's decision).

    One row per address (`uq_freelancers_email_lower`): a person who submits twice has
    corrected their application, and the second submission updates the first. `stato`
    and `note` are the admin's, never the applicant's."""

    __tablename__ = "freelancers"

    nome: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    cognome: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    linkedin_url: Mapped[str | None] = mapped_column(String(LINKEDIN_URL_MAX_LENGTH), default=None)
    cv_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    cv_filename: Mapped[str] = mapped_column(String(CV_FILENAME_MAX_LENGTH), nullable=False)
    cv_mime: Mapped[str] = mapped_column(String(CV_MIME_MAX_LENGTH), nullable=False)
    cv_size: Mapped[int] = mapped_column(Integer, nullable=False)
    tariffa_giornaliera: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    posizione: Mapped[str] = mapped_column(String(POSIZIONE_MAX_LENGTH), nullable=False)
    remoto: Mapped[str] = mapped_column(String(10), nullable=False)
    links: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    stato: Mapped[str] = mapped_column(String(20), nullable=False, default="nuovo")
    note: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (
        Index("uq_freelancers_email_lower", func.lower(email), unique=True),
        Index("ix_freelancers_created_at", "created_at"),
    )


class Company(Base, PrimaryKeyMixin, TimestampMixin, UtmMixin):
    """A company that needs people: the project in a few lines, from when and for how
    long, and what a day is worth to them. Several rows per company are fine -- a company
    has several projects -- so nothing is unique here but the id."""

    __tablename__ = "companies"

    nome_azienda: Mapped[str] = mapped_column(String(AZIENDA_MAX_LENGTH), nullable=False)
    referente: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    progetto: Mapped[str] = mapped_column(Text, nullable=False)
    periodo_da: Mapped[date] = mapped_column(Date, nullable=False)
    durata: Mapped[str] = mapped_column(String(DURATA_MAX_LENGTH), nullable=False)
    budget_giornaliero: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stato: Mapped[str] = mapped_column(String(20), nullable=False, default="nuovo")
    note: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (Index("ix_companies_created_at", "created_at"),)
