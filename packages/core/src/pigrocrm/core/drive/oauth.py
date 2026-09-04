"""Authorization-code flow with PKCE, server-side -- the Drive twin of
`gmail/oauth.py` (spec 9 §5.1-5.2).

Everything that module's docstring says about PKCE and the single-use state applies
here unchanged: the `code_verifier` never leaves `google_oauth_states`, the `state`
parameter is a fresh, unguessable jti redeemed by one conditional `UPDATE ... WHERE
consumed_at IS NULL`, and that redemption is committed before anything that can fail.
Both flows share that one table (`GoogleOAuthState.purpose` says which), so this
service reuses `GmailRepository.add_state`/`consume_state` rather than repeating the
race-safe redemption logic a second time -- see `drive/repository.py`'s docstring.

**Why a second grant, and not a wider Gmail one.** `drive/models.py`'s docstring
states the reason at length: a person can hold, revoke and reconnect a Drive
consent independently of their mailbox consent, so the CRM asks for a second,
separate authorisation rather than folding `drive.readonly`/`drive.file` into the
scopes Gmail already requests. `google_sub` on the two rows will normally agree --
one person's Google identity -- but they are not the same grant and the two tables
share no foreign key.

**The cross-identity check (spec 9 §5.2).** Two independent grants can still point at
two different Google identities if someone picks a different account in Google's
chooser -- deliberately or by mistake. That would build a CRM installation whose
mailbox and whose Drive belong to two different people, with no way to notice short of
comparing the two rows by hand. So each flow's `complete` reads the *other* table for
the same CRM user and refuses when a connected row there names a different `sub`.
Only `sub` is compared here, not the address: unlike the mailbox-reconnection check in
`GmailOAuthService`, nothing downstream is filed against a Drive address, so the
narrower, stabler identifier is the whole check. The refusal happens after the token
exchange -- there is no `sub` to compare before it -- and before anything is stored,
so a mismatched grant never overwrites a Drive credential that still belongs to the
right identity.
"""

import base64
import hashlib
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, decode_google_token_key, require_gmail_configured
from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.repository import DriveRepository
from pigrocrm.core.drive.schemas import DRIVE_REQUESTED_SCOPES, GoogleDriveAccountRead
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.crypto import seal
from pigrocrm.core.gmail.models import GoogleOAuthState
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.tokens import GOOGLE_AUTH_URL, GoogleTokenClient, TokenGrant

STATE_TTL_MINUTES = 5
# Testing-mode consumer refresh tokens expire seven days after consent -- the same
# Google behaviour `gmail/oauth.py`'s constant of the same name documents, and the
# same reason the CRM cannot detect it any other way.
UNVERIFIED_CONSENT_DAYS = 7
_VERIFIER_BYTES = 48  # 64 base64url characters, inside PKCE's 43-128 range
_JTI_BYTES = 24

_CONNECT_ACTION = "collegare Google Drive"
_DISCONNECT_ACTION = "scollegare Google Drive"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class GoogleDriveOAuthService:
    def __init__(self, session: Session, *, settings: Settings, tokens: GoogleTokenClient) -> None:
        self.session = session
        self.settings = settings
        self.tokens = tokens
        self.repo = DriveRepository(session)
        # Gmail's own repository, reused for two things that are Gmail's own tables:
        # the shared state row (by `purpose`, not duplicated -- see the module
        # docstring) and the mailbox row the cross-identity check below reads.
        self.gmail = GmailRepository(session)
        self.activities = ActivityService(session)

    @property
    def redirect_uri(self) -> str:
        return f"{self.settings.public_url.rstrip('/')}/api/drive/oauth/callback"

    def start(self, actor: Actor) -> str:
        require_gmail_configured(self.settings)
        actor.require_write(_CONNECT_ACTION)
        if actor.id is None:
            raise Conflict("google_drive_account", "solo un utente può collegare Google Drive")

        verifier = _b64url(os.urandom(_VERIFIER_BYTES))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        jti = _b64url(os.urandom(_JTI_BYTES))
        now = datetime.now(UTC)
        self.gmail.add_state(
            GoogleOAuthState(
                jti=jti,
                code_verifier=verifier,
                user_id=actor.id,
                expires_at=now + timedelta(minutes=STATE_TTL_MINUTES),
                purpose="drive",
            )
        )
        # Committed here and not at the end of the request, for the same reason
        # `GmailOAuthService.start` commits: the user is about to leave for Google, and
        # a state that only exists in an open transaction would be unredeemable by the
        # callback that follows.
        self.session.commit()

        return f"{GOOGLE_AUTH_URL}?" + urlencode(
            {
                "client_id": self.settings.google_client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(DRIVE_REQUESTED_SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "false",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": jti,
            }
        )

    def complete(self, *, code: str, state: str, actor: Actor) -> GoogleDriveAccountRead:
        require_gmail_configured(self.settings)
        actor.require_write(_CONNECT_ACTION)
        now = datetime.now(UTC)
        if actor.id is None:
            raise self._invalid_authorisation()

        row = self.gmail.consume_state(state, now, purpose="drive")
        if row is None:
            raise self._invalid_authorisation()
        # The redemption stands whatever happens next -- see the module docstring.
        self.session.commit()
        if row.user_id != actor.id:
            raise self._invalid_authorisation()

        grant = self.tokens.exchange_code(
            code=code, code_verifier=row.code_verifier, redirect_uri=self.redirect_uri
        )
        if not grant.subject or not grant.email_address:
            raise Conflict(
                "google_drive_account",
                "Google non ha restituito l'identità dell'account: riprova, e se "
                "l'errore persiste ricomincia da Impostazioni → Drive",
            )

        mailbox = self.gmail.account_for_user(actor.id)
        # Skipped once the mailbox has been explicitly disconnected, for the same
        # reason `GmailOAuthService.complete`'s own cross-check skips a disconnected
        # row: there is nothing left for a Drive grant to conflict with.
        if (
            mailbox is not None
            and mailbox.disconnected_at is None
            and mailbox.google_sub != grant.subject
        ):
            raise Conflict(
                "google_drive_account",
                "questo Drive appartiene a un account Google diverso dalla casella "
                f"collegata ({mailbox.email_address}): usa lo stesso account",
            )

        existing = self.repo.account_for_user(actor.id)
        account = self._store(existing, grant, actor.id, now)
        # The cached access token belongs to a grant that no longer applies.
        self.tokens.forget(account.id)
        # Last thing before the commit: ActivityService.record flushes and joins this
        # transaction, so nothing may commit after it on this session.
        self.activities.record(
            "google_drive_account",
            account.id,
            "drive.account_collegato",
            actor,
            {"email_address": account.email_address, "scopes_granted": list(grant.scopes)},
        )
        self.session.commit()
        return GoogleDriveAccountRead.model_validate(account)

    def disconnect(self, actor: Actor) -> None:
        """Mirrors `GmailOAuthService.disconnect`, minus the messages: Drive stores no
        correspondence, so there is nothing here for a `delete_messages` flag to name.
        """
        actor.require_write(_DISCONNECT_ACTION)
        if actor.id is None:
            raise Conflict("google_drive_account", "solo un utente può scollegare Google Drive")
        account = self.repo.account_for_user(actor.id)
        if account is None:
            raise Conflict("google_drive_account", "nessun account Google Drive collegato")

        # `disconnected`, not `revoked` -- the same split, for the same reason, as
        # `GoogleAccount.status`'s docstring works through for Gmail.
        account.status = "disconnected"
        account.disconnected_at = datetime.now(UTC)
        # Overwritten, not merely dereferenced: leaving the ciphertext behind means the
        # credential is still in every backup taken after the disconnect.
        account.refresh_token_ciphertext = b""
        account.refresh_token_nonce = b""
        self.tokens.forget(account.id)
        self.activities.record(
            "google_drive_account",
            account.id,
            "drive.account_scollegato",
            actor,
            {"email_address": account.email_address},
        )
        self.session.commit()

    # --- internals -------------------------------------------------------------------

    @staticmethod
    def _invalid_authorisation() -> Conflict:
        """One sentence for every pre-ownership failure, carrying no details at all --
        see `GmailOAuthService._invalid_authorisation` for why `details` is empty."""
        return Conflict(
            "google_drive_account",
            "questa autorizzazione non è più valida: ricomincia da Impostazioni → Drive",
        )

    def _store(
        self, existing: GoogleDriveAccount | None, grant: TokenGrant, user_id: UUID, now: datetime
    ) -> GoogleDriveAccount:
        ciphertext, nonce = seal(grant.refresh_token, decode_google_token_key(self.settings))
        # No CRM-imposed expiry (spec 9 §5.6): only Google's Testing-mode window,
        # exactly as `GmailOAuthService._store` computes it for the mailbox credential.
        consent_expires_at = (
            now + timedelta(days=UNVERIFIED_CONSENT_DAYS)
            if self.settings.google_app_unverified
            else None
        )
        account = existing or GoogleDriveAccount(user_id=user_id)
        if existing is None:
            self.session.add(account)
        elif existing.disconnected_at is not None:
            account.connected_at = now
        account.google_sub = grant.subject
        account.email_address = grant.email_address
        account.refresh_token_ciphertext = ciphertext
        account.refresh_token_nonce = nonce
        account.scopes_granted = list(grant.scopes)
        account.status = "active"
        account.consent_expires_at = consent_expires_at
        # A fresh grant answers whatever the last one failed at; leaving the old error
        # visible would show the user a warning about a credential that no longer
        # exists. `root_folder_ids`/`storage_folder_id` are untouched -- they are
        # Drive's own configuration, not part of this grant.
        account.last_error = None
        account.last_error_at = None
        account.disconnected_at = None
        self.session.flush()
        return account
