from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
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


class GmailMessage(Base, PrimaryKeyMixin, TimestampMixin):
    """One synchronised message.

    The unique constraint on `(google_account_id, gmail_message_id)` is what makes the
    watermark's deliberate 24-hour overlap free and every re-run idempotent, *and* it is
    the only thing that holds when two cycles overlap in time: a `SELECT` before the
    `INSERT` is a check both of them pass. the previous system kept its send record in a JSON file on
    disk with a non-atomic read-modify-write, so two concurrent sends lost the count; a
    unique constraint cannot lose anything.

    Like `GoogleAccount`, this class deliberately has no `__repr__`. `body_text` holds
    somebody's private correspondence, and a generated `repr` would print it into every
    traceback, every `logger.debug("%s", row)` and every pytest failure dump.

    `String(998)` on the header columns is RFC 5322's maximum line length minus the
    field name: the real bound rather than a guessed one.
    """

    __tablename__ = "gmail_messages"
    __table_args__ = (
        UniqueConstraint(
            "google_account_id", "gmail_message_id", name="uq_gmail_messages_account_message"
        ),
        # The thread view reads a whole conversation in date order, which is the only
        # access pattern this table has that is not a lookup by gmail id.
        Index("ix_gmail_messages_thread_date", "gmail_thread_id", "internal_date"),
    )

    google_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("google_accounts.id", ondelete="CASCADE"), nullable=False
    )
    gmail_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id_header: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    in_reply_to: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    # `Text`, not `String(998)`: `References` accumulates one Message-ID per reply and a
    # long thread runs past any line limit, folded across several lines.
    references: Mapped[str] = mapped_column(Text, nullable=False, default="")
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    to_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cc_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    snippet: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    internal_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    body_html_scartato: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # name, mime, size. No bytes, ever (spec 5.4).
    attachments: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )


class GmailMessageLink(Base, PrimaryKeyMixin, TimestampMixin):
    """Many-to-many, and not three nullable foreign keys: one email concerns the
    person, that person's customer and a deal all at once, and a single FK would force
    a choice the data does not support."""

    __tablename__ = "gmail_message_links"
    __table_args__ = (
        UniqueConstraint(
            "gmail_message_id", "entity_type", "entity_id", name="uq_gmail_message_links_triple"
        ),
        Index("ix_gmail_message_links_entity", "entity_type", "entity_id"),
    )

    gmail_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("gmail_messages.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Deliberately not a foreign key: it points at a customer, a person or a deal
    # depending on `entity_type`, and no single FK can express that. The `resolve` of
    # `gmail/roster.py` is what keeps it pointing at rows that exist.
    entity_id: Mapped[UUID] = mapped_column(nullable=False)


class GmailKnownAddress(Base, PrimaryKeyMixin, TimestampMixin):
    """Which roster addresses this account has already looked for.

    This is how "an address added to the CRM gets backfilled" happens *without*
    `PersonService` learning what Gmail is. The Gmail service compares the roster
    against this table at the start of each cycle and treats the difference as a
    backfill -- so a new address is synchronised on the next cycle, not in the instant
    it was saved, and the interface says so (spec 4.4) instead of leaving the user to
    discover it.

    Per account, and the unique constraint says so: two users may both correspond with
    the same client, and each mailbox has to be searched back over that address once on
    its own. A global register would give whichever mailbox synced second nothing.

    Deliberately not a column on `people` or `customers`. A CRM row is not the place to
    record what one particular Google mailbox has been asked; putting it there would
    also mean a customer's address could only ever be backfilled for one user, and it
    would make the address book carry Gmail's bookkeeping into every other feature.
    """

    __tablename__ = "gmail_known_addresses"
    __table_args__ = (
        UniqueConstraint("google_account_id", "address", name="uq_gmail_known_addresses"),
    )

    google_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("google_accounts.id", ondelete="CASCADE"), nullable=False
    )
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    # When this mailbox first went looking for that address. Kept because it is the only
    # answer to "why did three months of mail from this person appear on Tuesday".
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
