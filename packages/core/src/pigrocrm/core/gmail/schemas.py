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
