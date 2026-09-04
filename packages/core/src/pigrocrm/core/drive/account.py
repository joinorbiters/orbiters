"""The Drive credential's state, and the gate that separates it from the folders it
grants access to -- the Drive twin of `gmail/account.py`.

That module's docstring draws the one distinction this file must not blur either:
*is the credential healthy?* is `status`; *is this feature available?* is derived from
`scopes_granted` at the point of use. A Drive grant missing `drive.file` still lets the
CRM read from `root_folder_ids` -- it is only writing into `storage_folder_id` that is
unavailable -- so `health` reports that scope as merely missing, never as a reason to
paint the whole banner red.

Four statuses, the same four `GoogleAccount.status` carries and for the same reason
(see that model's docstring, and `GoogleDriveAccount`'s): nothing, wait, re-consent,
re-connect. `disconnected` is a user's own action and gets no banner, for the same
reason it gets none for Gmail -- a Drive the person unhooked on purpose is not a fault.

`root_folder_ids`/`storage_folder_id` are Drive's own configuration, not the
credential, which is why `set_roots` lives here rather than in `drive/oauth.py`:
writing them is a settings change, not a re-consent, and it commits on its own
transaction the same way `GoogleAccountService.set_store_bodies` does. Verifying the
chosen `storage_folder_id` is actually writable is 9D's job (the first real call
against Drive); this module only ever writes ids a person typed, never dereferences
them.

One new `activities` kind lives here: `drive.radici_impostate`, alongside
`drive.credenziale_revocata` -- `activities.kind` is open by project (slice 1 §5.8),
so neither costs a migration.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, gmail_configured
from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.repository import DriveRepository
from pigrocrm.core.drive.schemas import (
    DRIVE_SCOPE_FILE,
    DRIVE_SCOPE_READONLY,
    DriveBannerReason,
    DriveHealth,
    DriveRootsUpdate,
    GoogleDriveAccountRead,
)
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.errors import ConsentExpired, CredentialRevoked

# The same 48-hour lead as Gmail's `CONSENT_WARNING_HOURS`: one Google OAuth client
# grants both credentials, so Testing-mode's seven-day window and the moment a warning
# stops being one are the same arithmetic for either.
CONSENT_WARNING_HOURS = 48

# The one text for "there is nothing to act on" -- used whether the row is missing
# outright or was disconnected on purpose, exactly as `gmail/account.py`'s `_NO_ACCOUNT`
# answers both of its own callers with one sentence.
_NOT_CONNECTED = "Google Drive non è collegato: collegalo da Impostazioni → Drive"
_NOT_A_USER = "solo un utente può usare Google Drive"
_ROOTS_ACTION = "impostare le cartelle Drive"

_REVOKED_TEXT = (
    "Il consenso Google Drive per {email} è stato revocato: la lettura e la scrittura "
    "dei documenti sono sospese finché non ricolleghi Drive da Impostazioni → Drive."
)
_EXPIRING_TEXT = (
    "Il consenso Google Drive per {email} va rinnovato entro il {when}. "
    "Dopo quella data l'accesso ai documenti si interrompe."
)
_EXPIRED_TEXT = (
    "Il consenso Google Drive per {email} è scaduto e va rinnovato da "
    "Impostazioni → Drive: l'accesso ai documenti è fermo."
)
_SCOPE_TEXT = (
    "L'accesso ai documenti è spento: manca l'autorizzazione {scope}. "
    "Ricollega Drive da Impostazioni → Drive per concederla."
)


class GoogleDriveAccountService:
    def __init__(self, session: Session, *, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = DriveRepository(session)
        self.activities = ActivityService(session)

    def health(self, actor: Actor) -> DriveHealth:
        """One call answers the whole shell banner for Drive.

        No account at all is not a problem to report: an installation that never
        connected Drive has nothing to say about it, and a banner there would be an
        error message for a feature nobody switched on.
        """
        # Read here, not taken from the caller, for the same reason
        # `GoogleAccountService.health` reads it itself: one Google OAuth client
        # serves both credentials, so whether *Google* is configured at all is a fact
        # about the installation, not about which grant an adapter remembered to ask.
        configured = gmail_configured(self.settings)
        account = self.repo.account_for_user(actor.id) if actor.id else None
        if account is None:
            return DriveHealth(
                account=None,
                banner=None,
                banner_text=None,
                missing_scopes=[],
                configured=configured,
            )

        read = GoogleDriveAccountRead.model_validate(account)
        missing = [
            scope
            for scope in (DRIVE_SCOPE_READONLY, DRIVE_SCOPE_FILE)
            if scope not in account.scopes_granted
        ]
        now = datetime.now(UTC)

        def answer(banner: DriveBannerReason, text: str | None) -> DriveHealth:
            """Every branch below answers with the same account and the same scope
            list; only the cause and its sentence differ -- written once so a new
            cause cannot be added that forgets to report `missing_scopes`."""
            return DriveHealth(
                account=read,
                banner=banner,
                banner_text=text,
                missing_scopes=missing,
                configured=configured,
            )

        # Order matters, and it is an order of actionability -- the same order
        # `GoogleAccountService.health` follows for the same reason: revoked is the
        # most final, so it wins over everything below it.
        if account.status == "revoked":
            return answer("revoked", _REVOKED_TEXT.format(email=account.email_address))
        if account.status == "disconnected":
            # Nothing is wrong: the user unhooked Drive on purpose.
            return answer(None, None)
        # A date already past is inside "within 48 hours" by arithmetic, so it is
        # caught here rather than reported as a gentle heads-up about the future.
        if account.status == "expired" or (
            account.consent_expires_at is not None and account.consent_expires_at <= now
        ):
            return answer("expired", _EXPIRED_TEXT.format(email=account.email_address))
        if account.consent_expires_at is not None and account.consent_expires_at - now <= timedelta(
            hours=CONSENT_WARNING_HOURS
        ):
            return answer(
                "expiring",
                _EXPIRING_TEXT.format(
                    email=account.email_address,
                    # The day, not "presto": the date is what lets somebody decide
                    # whether this is a thing for now or a thing for Monday.
                    when=account.consent_expires_at.strftime("%d/%m/%Y alle %H:%M"),
                ),
            )
        if DRIVE_SCOPE_READONLY in missing:
            # Only the read scope raises a banner. A grant missing `drive.file` can
            # still read every configured root, which is most of the feature;
            # `missing_scopes` carries that fact to the settings page without a
            # banner over the whole app -- the same treatment Gmail gives a missing
            # `gmail.send`.
            return answer("scope_missing", _SCOPE_TEXT.format(scope=DRIVE_SCOPE_READONLY))
        return answer(None, None)

    def usable(self, actor: Actor, *, scope: str, feature: str) -> GoogleDriveAccount:
        """The gate. Called **before** anything is composed and before any HTTP call
        is made, mirroring `GoogleAccountService.usable` for the same reason: somebody
        who asks to read a folder from a revoked account learns it at the ask rather
        than from a failed Drive call.

        This class is constructed from a session and settings and holds no transport,
        which is what makes "no HTTP call" a property of the code rather than a
        promise: there is nothing here to call Google *with*.
        """
        account = self._present(actor)
        if account.status == "expired":
            raise ConsentExpired(account.id, account.email_address)
        if account.status != "active":
            raise CredentialRevoked(account.id, account.email_address)
        if scope not in account.scopes_granted:
            # Not a credential problem: `status` stays `active` and every other scope
            # keeps working. It is this feature that is unavailable.
            raise Conflict(
                "google_drive_account",
                f"{feature} non è disponibile: manca l'autorizzazione {scope}. "
                "Ricollega Drive da Impostazioni → Drive per concederla.",
                scope=scope,
                feature=feature,
            )
        return account

    def mark_revoked(self, account: GoogleDriveAccount, actor: Actor, reason: str) -> None:
        """Terminal. Mirrors `GoogleAccountService.mark_revoked`: called from the one
        place that can learn it -- a refresh answering `invalid_grant` -- and committed
        on its own behalf because the operation that discovered this is about to raise,
        and its own transaction will be rolled back by whoever catches it.

        `actor` is `Actor.system()` at every call site: Google revoked this, nobody in
        this CRM did. `reason` is the sentence the user reads, carrying no upstream
        prose, no error code and no token -- a parameter and not something derived
        from the exception here.
        """
        account.status = "revoked"
        account.last_error = reason
        account.last_error_at = datetime.now(UTC)
        self.activities.record(
            "google_drive_account",
            account.id,
            "drive.credenziale_revocata",
            actor,
            # The address and nothing else -- never the upstream body.
            {"email_address": account.email_address},
        )
        self.session.commit()

    def set_roots(self, data: DriveRootsUpdate, actor: Actor) -> GoogleDriveAccountRead:
        """Which folders the CRM may read from, and which one it may write into.

        Reached through `_present`, which is `usable`'s own presence check and refuses
        the same way for the same reason: a Drive that is not connected has no
        folders to configure. Unlike `usable`, a revoked or expired credential is
        still allowed through here -- fixing the folder list is not a use of the
        credential, and the person most likely to be looking at this screen is the
        one trying to recover from exactly that state. Verifying that
        `storage_folder_id` is actually writable is 9D's job, at the first real call;
        this method only ever stores ids a person typed.
        """
        actor.require_write(_ROOTS_ACTION)
        account = self._present(actor)
        account.root_folder_ids = list(data.root_folder_ids)
        account.storage_folder_id = data.storage_folder_id
        # Last thing before the commit: ActivityService.record flushes and joins this
        # transaction, so nothing may commit after it on this session.
        self.activities.record(
            "google_drive_account",
            account.id,
            "drive.radici_impostate",
            actor,
            {
                "root_folder_ids": list(data.root_folder_ids),
                "storage_folder_id": data.storage_folder_id,
            },
        )
        self.session.commit()
        return GoogleDriveAccountRead.model_validate(account)

    # --- internals -------------------------------------------------------------------

    def _present(self, actor: Actor) -> GoogleDriveAccount:
        """This actor's Drive account, connected, or the one `Conflict` that answers
        every way it might not be.

        `disconnected` is folded into the same refusal as "no row at all", not treated
        as its own branch here: both mean there is nothing left to gate a use of, or a
        folder to configure, on. `health` is the one place that tells a user's own
        disconnect apart from never having connected -- this gate does not need to.
        """
        if actor.id is None:
            raise Conflict("google_drive_account", _NOT_A_USER)
        account = self.repo.account_for_user(actor.id)
        if account is None or account.status == "disconnected":
            raise Conflict("google_drive_account", _NOT_CONNECTED)
        return account
