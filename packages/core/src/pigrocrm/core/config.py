import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pigrocrm.core.errors import Conflict

# RFC 7518 Section 3.2: an HS256 key shorter than 32 bytes is weaker than the
# algorithm's own output size. PyJWT already warns about this; validating here turns
# a silent warning (easy to miss in production logs) into a startup failure instead.
MIN_JWT_SECRET_LENGTH = 32

# AES-256-GCM, which is what encrypts `google_accounts.refresh_token_ciphertext`.
GOOGLE_TOKEN_KEY_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIGROCRM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pigrocrm:pigrocrm@localhost:5432/pigrocrm"
    jwt_secret: str = "change-me-in-production-please-set-a-real-secret"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
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

    # Storage. `local` by default: no external dependency is what makes the product
    # genuinely self-hostable (spec 5). Switching to `gdrive` moves *new* bytes only
    # -- the ones already written stay where they are, and moving them is an explicit
    # migration, not a side effect of an environment variable.
    storage_backend: Literal["local", "gdrive"] = "local"
    storage_local_root: str = "./var/documents"
    # The service account's JSON key, inline. `PIGROCRM_GDRIVE_ROOT_FOLDER_ID` must
    # name a folder on a Shared Drive (or one shared with the service account): a
    # service account has no Drive quota of its own and `files.create` otherwise
    # fails with storageQuotaExceeded. `storage_from_settings` checks this at startup
    # (`GDriveStorage.verify_root_accessible`) rather than at the first upload.
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
