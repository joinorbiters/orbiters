from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Mirror the column widths in gmail/models.py exactly.
GOOGLE_SUB_MAX_LENGTH = 255
EMAIL_ADDRESS_MAX_LENGTH = 320
STATUS_MAX_LENGTH = 10
LAST_ERROR_MAX_LENGTH = 500
JTI_MAX_LENGTH = 64
CODE_VERIFIER_MAX_LENGTH = 128

GmailStatus = Literal["active", "expired", "revoked"]

SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
# `openid` + `email` identify *which* mailbox was connected: without the stable `sub`
# there is no way to refuse a reconnection that points at a different mailbox by
# mistake and silently relabels the entire history.
REQUESTED_SCOPES: tuple[str, ...] = ("openid", "email", SCOPE_READONLY, SCOPE_SEND)


class GoogleAccountRead(BaseModel):
    """What the settings page and `describe_gmail_account` show. No token, in either
    form: not the plaintext, not the ciphertext, not the nonce."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email_address: str
    scopes_granted: list[str]
    status: GmailStatus
    consent_expires_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    last_sync_at: datetime | None
    sync_watermark: datetime | None
    gmail_store_bodies: bool
    connected_at: datetime
    disconnected_at: datetime | None


class SyncReport(BaseModel):
    """What one cycle did. Returned by the REST endpoint and by the MCP tool, so an
    agent can diagnose instead of retrying.

    Deliberately not `frozen`: `sync()` fills the counters in as the cycle runs, so that
    a report exists -- and is truthful about how far the cycle got -- at every point
    rather than only at the end.

    Every field is a number, a timestamp or a flag. There is no room in it for a
    subject, an address or a body, which is what makes it safe to log and to hand to an
    agent.
    """

    started_at: datetime
    already_running: bool = False
    running_since: datetime | None = None
    queries_issued: int = 0
    threads_fetched: int = 0
    messages_stored: int = 0
    messages_skipped: int = 0
    links_created: int = 0
    states_pruned: int = 0


class GmailMessageRead(BaseModel):
    """One stored message, as the API and the MCP surface show it.

    Read-only, so no `max_length` and no `SafeStr` anywhere: nothing here is ever an
    input. `body_text` is empty when the account has `gmail_store_bodies` off, which is
    the declared degradation of spec 5.4 and not a missing value.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gmail_message_id: str
    gmail_thread_id: str
    direction: Literal["inbound", "outbound"]
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    subject: str
    snippet: str
    internal_date: datetime
    body_text: str
    body_truncated: bool
    body_html_scartato: bool
    attachments: list[dict[str, object]]
