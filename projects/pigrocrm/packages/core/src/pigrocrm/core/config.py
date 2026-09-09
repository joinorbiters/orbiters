import base64
import binascii
from functools import lru_cache
from typing import Literal
from zoneinfo import available_timezones

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pigrocrm.core.errors import Conflict

# RFC 7518 Section 3.2: an HS256 key shorter than 32 bytes is weaker than the
# algorithm's own output size. PyJWT already warns about this; validating here turns
# a silent warning (easy to miss in production logs) into a startup failure instead.
MIN_JWT_SECRET_LENGTH = 32

# AES-256-GCM, which is what encrypts `google_accounts.refresh_token_ciphertext`.
GOOGLE_TOKEN_KEY_BYTES = 32

# The default ceiling on the text of one file, wherever it was read from: a file on
# Drive (`drive/reader.py::read_text`) or a document archived in the CRM
# (`documents/service.py::read_text`). One number for both, because it answers one
# question -- how much of somebody else's document a single answer may carry.
# A module constant as well as a field default because `DriveReader` takes the number,
# not a `Settings`: it is a reader of Drive, not of this installation's configuration,
# and `drive_reader_for` is the one place the two meet. Same 256 KB as
# `gmail_body_max_bytes`, and for the same reason -- a generous limit that only bites
# on the anomalous, so that what a person reads is the document and not a policy.
TEXT_MAX_BYTES_DEFAULT = 262_144


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIGROCRM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pigrocrm:pigrocrm@localhost:5432/pigrocrm"
    # The Orbiters signup list (docs/superpowers/specs/2026-09-07-orbiters-landing-design.md)
    # lives in a database of its own, not in the CRM schema above. Empty means "the same
    # server and credentials as `database_url`, database named `orbiters`"; set it only to
    # put that list somewhere else. `orbiters.database.ensure_orbiters_database` creates
    # the database if it is missing, which needs CREATE DATABASE on the server.
    orbiters_database_url: str = ""
    # --- ChatGPT Ads: the Orbiters signup conversion ---------------------------------
    # The pixel measures the signup from the browser; these values are the server half
    # (`orbiters/conversions.py`), which exists because the browser event is the one
    # that gets lost: an ad blocker, a network that drops the SDK, a tab closed before
    # the ping leaves.
    #
    # `openai_pixel_id` is public -- it sits in the website's markup in the clear -- and
    # is repeated here because the conversions endpoint wants it in the query string.
    # `openai_conversions_api_key` is a secret with read and write access to the
    # conversion data source: it lives in the server's `.env`, in no file of this
    # repository and in no page. With either one empty (the default) no server event is
    # sent, and that is not an error: it is an installation that runs no campaigns.
    openai_pixel_id: str = ""
    openai_conversions_api_key: str = ""
    # The URL of the page where the conversion happens. Required by the API for a `web`
    # event, and taken from here rather than from the request: a `source_url` that
    # arrives from the client is a string the caller chose, and it would be forwarded to
    # a third party exactly as it came.
    orbiters_signup_url: str = "https://joinorbiters.com/orbiters"
    # Whether to also send OpenAI the SHA-256 of the address. It improves attribution,
    # and a hash of an email is still that person's identifier: it is a decision for
    # whoever runs the site, so the default is no. IP and user agent travel either way --
    # they are the request itself, which the pixel in the browser shows in any case.
    openai_conversions_send_hashed_email: bool = False
    # The registry of spaces -- which slug maps to which database; see
    # docs/superpowers/specs/2026-09-08-spazi-un-database-per-tenant-design.md. Same rule
    # as `orbiters_database_url`: empty means the CRM's own server and credentials,
    # database `pigrocrm_tenants`. Each space's own database is created beside it by
    # `tenants.service.TenantService.provision`.
    tenants_database_url: str = ""
    # Where `alembic.ini` lives, for migrating a freshly created space's database with
    # the same env.py production runs. Empty resolves to packages/core/alembic.ini next
    # to this package, which is where both the checkout and the API image keep it.
    tenants_alembic_ini: str = ""
    # The root installation's own name as a space, e.g. `humancraft`: `/<root_slug>/app`
    # and `/<root_slug>/api` are the root itself -- same database, same Gmail and Drive,
    # same cookies -- so the titolare's CRM has an address shaped like everyone else's.
    # Empty means the root answers only without a prefix. Reserved for signups when set.
    root_slug: str = ""
    jwt_secret: str = "change-me-in-production-please-set-a-real-secret"
    access_token_minutes: int = 15
    # Six months, sliding: `/api/auth/refresh` consumes the old jti and issues a new row
    # whose expiry is measured from now, so anyone who uses the CRM never sees the login
    # again and anyone who leaves it for six months does (spec 9 §5.6). The access token
    # stays at fifteen minutes: that is the revocation window, not the session length.
    refresh_token_days: int = 180
    # Must stay True in production: it is what stops the auth cookies from ever being
    # sent over plain HTTP. It exists as a *setting* rather than a hardcoded True only
    # because of one browser: Chrome and Firefox treat "localhost" as a secure context
    # and accept a `Secure` cookie over plain HTTP there, but Safari does not and has
    # no plan to. Local development (slice 1B's Vite proxy) serves the API over
    # http://localhost with no TLS, so without an escape hatch, login on Safari in dev
    # would return 200 while the browser silently discarded the cookie -- every
    # request after that looks unauthenticated with no error anywhere to explain why.
    # Set PIGROCRM_COOKIE_SECURE=false for that one case. Anyone tempted to flip this
    # in production because "it's just a flag" should re-read this paragraph first.
    cookie_secure: bool = True

    # Whether a personal access token may perform the sixteen operations listed in
    # `actor.AGENT_FORBIDDEN_ACTIONS` -- issuing and annulling invoices, the fiscal
    # profile, rates, cost categories, period locks, the hours-to-invoice bridge and the
    # annual estimate -- plus sending mail and preparing a payment reminder.
    #
    # `False` by default, and the default is the one nobody has to think about. Those
    # operations are not merely privileged, they are **irreversible in ways the rest of
    # the product is not**: issuing consumes a number from a gap-free fiscal register
    # that cannot be handed back, and a sent email is in somebody's client's inbox. The
    # worst outcome is not "the agent made a mistake" but "the agent made a mistake and
    # nobody can undo it".
    #
    # Turning it on is a decision about a *specific installation*, which is why it is a
    # setting and not a code change: this product is single-tenant and self-hosted, and
    # the person running it may reasonably want their own agent to do everything they
    # can. Everyone else keeps the closed default without having to know it exists.
    #
    # The flag is read once, in `PatService.resolve`, and stamped onto the `Actor` it
    # builds -- so the capability travels on the credential rather than living in a
    # global that a caller could be unaware of. That is deliberate: it means a REST
    # request presenting the same token is treated exactly like the MCP transport
    # (see the reasoning in `actor.py`), and it is the first step toward residuo R10,
    # where a token would say what it is *for* instead of inheriting everything.
    mcp_full_access: bool = False

    # The emitter's timezone, and the only one. Every `Date` column in the product is a
    # calendar day in *this* zone: `invoices.data_emissione` (slice 3 §6.2),
    # `costs.data` and `time_entries.data` (slice 4), `deals.chiuso_il` and
    # `documents.stato_dal` (slice 6 §4.1). Deriving any of them from
    # `datetime.now(UTC).date()` moves everything after 23:00 CET by a day and everything
    # on 31 December by a year -- the exact defect slice 3 §6.2 names. Single-tenant, so
    # one zone: a per-user zone would mean the same invoice falling in two fiscal years
    # depending on who looked at it.
    #
    # It is a setting rather than a constant because `db/clock.py` is now the *only*
    # clock -- `clock.oggi_in_italia()` delegates to it -- so changing this changes the
    # fiscal calendar too, deliberately and in one place. An operator who moves it off
    # Europe/Rome is telling the product where the invoices are issued from, which is
    # the only reading under which one clock and one answer stay true.
    timezone: str = "Europe/Rome"

    # Storage. `local` by default: no external dependency is what makes the product
    # genuinely self-hostable (spec 5). Switching to `gdrive` moves *new* bytes only
    # -- the ones already written stay where they are, and moving them is an explicit
    # migration, not a side effect of an environment variable.
    #
    # `gdrive` is finished by one of two routes, and the environment chooses which:
    # either the two service-account variables below, or -- with neither of them set --
    # the Google account the titolare connects from Impostazioni → Drive, writing into
    # the folder they pick there. The second route has nothing to configure here: it
    # lives in a row, so `storage_from_settings` returns a storage that resolves it at
    # the first upload, and the API boots before Drive is connected. Naming either
    # service-account variable selects the first route and makes the other one required,
    # so a half-finished setup is refused by name instead of quietly using somebody's
    # personal credential -- when the MCP adapter starts, or at the API's first document
    # operation, which is when each of them builds its backend.
    storage_backend: Literal["local", "gdrive"] = "local"
    storage_local_root: str = "./var/documents"
    # The service account's JSON key, inline. `PIGROCRM_GDRIVE_ROOT_FOLDER_ID` must
    # name a folder on a Shared Drive (or one shared with the service account): a
    # service account has no Drive quota of its own and `files.create` otherwise
    # fails with storageQuotaExceeded. `storage_from_settings` checks it
    # (`GDriveStorage.verify_root_accessible`) while it builds the backend, rather than
    # leaving it to fail mid-upload: that is start-up on the MCP adapter and the first
    # document operation on the API, which is where `get_storage` resolves.
    gdrive_service_account_json: str = ""
    gdrive_root_folder_id: str = ""
    # Rendering. The image installs Pandoc and Typst at these names (Dockerfile.api).
    pandoc_binary: str = "pandoc"
    typst_binary: str = "typst"

    # --- Gmail (slice 5). Absent, not broken: if `google_client_id` is unset, Gmail
    # does not exist on this installation. The UI hides the section, the endpoints
    # answer Conflict, and the MCP tools are never registered. That is what lets
    # someone who self-hosts precisely in order not to have Google not have Google.
    google_client_id: str = ""
    # `repr=False` on the two secrets below, and nowhere else in this class: a
    # `Settings` object reaches logs, tracebacks and debugger frames, and both of these
    # are halves of a credential to a *third-party* account. The client id and the
    # public URL are not secrets and stay visible, because hiding them would only make
    # a misconfiguration harder to read.
    google_client_secret: str = Field(default="", repr=False)
    # 32 raw bytes, base64-encoded. Encrypts `google_accounts.refresh_token_ciphertext`
    # at rest. The key lives outside the database on purpose: a dump, a backup or a
    # pg_dump attached to a bug report are different exposure surfaces from the running
    # system, and this credential opens a *third-party* account, not just this app.
    google_token_key: str = Field(default="", repr=False)
    # The public origin, used to build the one redirect_uri Google compares exactly:
    # {public_url}/api/gmail/oauth/callback.
    public_url: str = ""
    # Google exposes no API for "is my OAuth client verified", so the operator states
    # it. True means Testing, which means a consumer refresh token expires 7 days after
    # consent -- so `consent_expires_at` gets set and the UI warns 48 hours ahead.
    google_app_unverified: bool = False

    gmail_sync_address_batch_size: int = 20
    gmail_backfill_days: int = 90
    gmail_watermark_overlap_hours: int = 24
    gmail_body_max_bytes: int = 262_144
    gmail_attachment_max_bytes: int = 20_971_520
    gmail_send_grace_minutes: int = 15
    # --- Drive (slice 9C). The text of one file the titolare pointed at, capped.
    # `ge=1` because a ceiling of zero would return an empty document for every file
    # and read as "this file has no text"; the upper bound is what an agent's context
    # and an HTTP response can carry without the cap being a fiction.
    drive_text_max_bytes: int = Field(default=TEXT_MAX_BYTES_DEFAULT, ge=1, le=10_485_760)
    # --- Documenti archiviati. The same ceiling for the text of a document already in
    # the CRM's own store. A separate field and not a reuse of the Drive one: an
    # installation that reads long contracts out of its archive has no reason to also
    # widen what a Drive folder may pour into an answer, and the two ceilings guard
    # bytes that arrive by different doors.
    document_text_max_bytes: int = Field(default=TEXT_MAX_BYTES_DEFAULT, ge=1, le=10_485_760)
    # Whether reconciliation may rely on Gmail preserving the Message-ID we supply.
    # Spec 6.3 requires this to be verified rather than assumed, because the fallback
    # (matching on recipient + subject + internalDate) is an approximate comparison and
    # cannot tell two near-identical sends apart. The check is recorded in
    # docs/superpowers/notes/2026-08-20-gmail-message-id-verification.md, and as of
    # today that note records **UNVERIFIED**: nobody has yet run it against a real
    # Gmail. The default stays `true` because the exact path is the one the design is
    # built around and the fallback is worse -- but it is an assumption about a third
    # party until that note says otherwise, and an operator who sees delivered mail
    # being reported as `fallito` should try `false` first.
    gmail_reconcile_by_message_id: bool = True

    # The three numbers that decide whether a reminder is legitimate, bearable and
    # finite. Each carries `ge`/`le` because they are plain integers that reach no
    # service-level range check: a `solleciti_grace_days` of `0` would chase the day
    # after the due date while the transfer is still in flight, and a
    # `solleciti_min_interval_days` of `0` would remove the layer that stops the double
    # send hours apart. The upper bounds are not tidiness either -- an operator who typed
    # a year into the grace period would silently switch the feature off, and one who
    # typed 50 into the ceiling would have configured a persecution.
    solleciti_grace_days: int = Field(default=7, ge=1, le=365)
    solleciti_min_interval_days: int = Field(default=14, ge=1, le=365)
    # 3 is also `MAX_SOLLECITO_LEVEL` in `gmail/solleciti_template.py`, which is where the
    # wording stops escalating: above it a fourth register would have to be a legal
    # threat, which is not a sentence this project has standing to put in a freelancer's
    # name. The `le` therefore matches the template rather than being a round number.
    solleciti_max_reminders: int = Field(default=3, ge=1, le=3)

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_must_be_long_enough(cls, value: str) -> str:
        if len(value) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"jwt_secret must be at least {MIN_JWT_SECRET_LENGTH} characters long "
                "(a short HS256 key is weaker than the algorithm itself, RFC 7518 "
                "Section 3.2)"
            )
        return value

    @field_validator("timezone")
    @classmethod
    def _timezone_must_be_a_real_zone(cls, value: str) -> str:
        # Checked against the tz database at construction, not at first use: a typo in
        # PIGROCRM_TIMEZONE must fail at start-up rather than shift every date in the
        # product by an hour for the life of the deployment. `ZoneInfo` itself would
        # raise on first use instead -- deep inside a repository, on whichever request
        # happened to need a date first.
        if value not in available_timezones():
            raise ValueError(
                f"timezone {value!r} is not in the IANA tz database (examples: Europe/Rome, UTC)"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


def gmail_configured(settings: Settings) -> bool:
    """All four or none. A client id with no token key would connect an account and
    then be unable to store its refresh token, which is a worse failure than not
    offering the feature."""
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_token_key
        and settings.public_url
    )


def require_gmail_configured(settings: Settings) -> None:
    if not gmail_configured(settings):
        raise Conflict("gmail", "Gmail non è configurato su questa installazione")


def decode_google_token_key(settings: Settings) -> bytes:
    """Raises `ValueError` naming the variable, never quoting the value.

    Called at startup when `google_accounts` has at least one row (apps/api deps),
    so a missing or malformed key fails the boot rather than the first sync -- the
    same discipline as `_jwt_secret_must_be_long_enough`. Not a pydantic validator,
    because the empty default has to stay legal for every install that has no Gmail.
    """
    if not settings.google_token_key:
        raise ValueError(
            "PIGROCRM_GOOGLE_TOKEN_KEY is not set, but google_accounts holds at least "
            "one stored refresh token. Without the key those rows cannot be decrypted."
        )
    try:
        key = base64.b64decode(settings.google_token_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        # `from exc` and not the value: `binascii.Error` quotes the offending input in
        # some builds, so the cause is kept for the traceback while this message -- the
        # one anything might format on its own -- names only the variable. The API's
        # handler renders `DomainError`, so a `ValueError` here reaches the process log
        # and nowhere else, which is the one place a malformed key belongs.
        raise ValueError("PIGROCRM_GOOGLE_TOKEN_KEY is not valid base64") from exc
    if len(key) != GOOGLE_TOKEN_KEY_BYTES:
        raise ValueError(
            f"PIGROCRM_GOOGLE_TOKEN_KEY must decode to exactly {GOOGLE_TOKEN_KEY_BYTES} "
            f"bytes for AES-256-GCM, got {len(key)}"
        )
    return key
