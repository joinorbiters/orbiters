from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class GoogleAccount(Base, PrimaryKeyMixin, TimestampMixin):
    """One connected mailbox, per CRM user.

    `status` has three values and not four, and the distinction is load-bearing:
    `expired` is what we *predicted* (the consent window has passed with no successful
    refresh since), `revoked` is what Google *told us* (`invalid_grant`). They call for
    different reactions -- the first is a warning to show early, the second a fact to
    record -- so they are two states.

    `scopes_granted` deliberately does not feed `status`. Capability is derived from it
    at the point of use; the health of the credential is `status`. Google may grant a
    subset, and an account with `gmail.send` but not `gmail.readonly` is a healthy
    credential on which sync is unavailable.

    Nothing on this class is safe to print. There is deliberately no `__repr__`:
    SQLAlchemy's declarative base does not add one, so the inherited `object.__repr__`
    prints the class and an address and nothing else, which is the behaviour the two
    `refresh_token_*` columns need from every traceback and every debugger frame.
    """

    __tablename__ = "google_accounts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    google_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
    # AES-256-GCM, key from PIGROCRM_GOOGLE_TOKEN_KEY. Never logged, never returned by
    # any schema, never in an exception message.
    refresh_token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes_granted: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    # When the *consent* must be renewed, not when an access token expires. Set to
    # connected_at + 7 days while PIGROCRM_GOOGLE_APP_UNVERIFIED is true, because that
    # is Google's Testing-mode behaviour and Google exposes no API to detect it.
    consent_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # The sentence the user reads, in Italian. Never a stack trace, never an upstream
    # body, never a token.
    last_error: Mapped[str | None] = mapped_column(String(500), default=None)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    sync_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Off means headers and Gmail's snippet only, with the read-through degradation of
    # spec 5.4 point 2 as a declared consequence rather than a hidden one.
    gmail_store_bodies: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class GoogleOAuthState(Base, PrimaryKeyMixin, TimestampMixin):
    """One in-flight authorisation.

    It exists because **PKCE's `code_verifier` has to stay server-side** between
    `/start` and `/callback`: putting it inside the signed `state` would make it
    readable by the browser and cancel PKCE entirely. It is also the registry that
    makes the JWT's `jti` single-use in fact rather than in principle.

    `consumed_at` is a nullable timestamp and not a boolean because single-use has to
    survive a race: the redemption is one conditional `UPDATE ... WHERE consumed_at IS
    NULL`, which Postgres serialises on the row lock, so two simultaneous callbacks
    produce exactly one winner. A read-then-write pair over a boolean would not.

    Expired rows are pruned on each sync cycle -- unlike `refresh_tokens`, which
    residuo R8 records as never pruned at all.
    """

    __tablename__ = "google_oauth_states"

    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
