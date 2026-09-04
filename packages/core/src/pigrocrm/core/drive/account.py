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
transaction the same way `GoogleAccountService.set_store_bodies` does.

`storage_folder_id` alone is dereferenced, and only when it is being set to a new,
non-null id: `set_roots` proves the folder exists, is visible to this credential, and
is actually a folder -- one `files.get` through the owner's own transport, before a
single column is written -- so a titolare who pastes the id of a file, a folder they
cannot see, or a typo learns it on the spot rather than on the CRM's first upload.
`root_folder_ids` are read roots and are never dereferenced here; they are verified at
the moment they are used, by the Drive reader. `transport_factory` exists solely so a
test can point that one `files.get` at a fake instead of Google -- production always
takes the default, `transport/user_transport_for`.

One new `activities` kind lives here: `drive.radici_impostate`, alongside
`drive.credenziale_revocata` -- `activities.kind` is open by project (slice 1 §5.8),
so neither costs a migration.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, gmail_configured
from pigrocrm.core.drive.errors import DriveConsentExpired, DriveCredentialRevoked
from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.query import FOLDER_MIME, file_meta_url
from pigrocrm.core.drive.repository import DriveRepository
from pigrocrm.core.drive.schemas import (
    DRIVE_SCOPE_FILE,
    DRIVE_SCOPE_READONLY,
    DriveBannerReason,
    DriveHealth,
    DriveRootsUpdate,
    GoogleDriveAccountRead,
)
from pigrocrm.core.drive.transport import DriveTransport, user_transport_for
from pigrocrm.core.errors import Conflict, ValidationFailed

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

# What the one `files.get` call in `_verify_storage_folder` tells the transport it is
# doing. `Conflict.details["what"]` carries this back, which is what tells a 404 there
# apart from a 404 anywhere else in the same call (the token endpoint, notably) -- see
# `_verify_storage_folder`'s own docstring.
_WHAT_VERIFY_STORAGE_FOLDER = "verifica della cartella di scrittura"
# The `feature` name `_verify_storage_folder` hands to `_missing_scope_conflict` when
# it refuses to call Drive at all over a missing `drive.readonly`. Distinct from
# `_WHAT_VERIFY_STORAGE_FOLDER` on purpose: that one names a Drive *call* that was
# made and failed, this one names the *feature* that a scope gate refused before any
# call happened -- the same distinction `usable`'s own `feature` parameter draws.
_FEATURE_VERIFY_STORAGE_FOLDER = "la verifica della cartella di scrittura"


def _missing_scope_conflict(scope: str, feature: str) -> Conflict:
    """The one sentence for "this Drive grant is active but missing a scope",
    shared by `usable` and `_verify_storage_folder` so the two gates -- one for using
    a configured Drive, one for choosing its write folder -- read identically to
    whoever hits either of them.
    """
    return Conflict(
        "google_drive_account",
        f"{feature} non è disponibile: manca l'autorizzazione {scope}. "
        "Ricollega Drive da Impostazioni → Drive per concederla.",
        scope=scope,
        feature=feature,
    )


class GoogleDriveAccountService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        transport_factory: Callable[[GoogleDriveAccount], DriveTransport] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.repo = DriveRepository(session)
        self.activities = ActivityService(session)
        # Production takes the default: a transport built from this row's own sealed
        # refresh token, the same composition `drive/reader.py` and `storage/
        # lazy_drive.py` use. A test supplies its own, over a fake of the network,
        # so `_verify_storage_folder`'s one `files.get` never dials out.
        self._transport_factory: Callable[[GoogleDriveAccount], DriveTransport] = (
            transport_factory
            if transport_factory is not None
            else lambda account: user_transport_for(account, self.settings)
        )

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

        `usable` itself performs no call -- it only reads the row and
        `scopes_granted`. That is no longer true of this *class*: `set_roots`'s own
        verification of a new `storage_folder_id` does reach Drive (see
        `_verify_storage_folder`), through a transport this class now holds a factory
        for. `usable` is not that call, and is not on its path -- fixing the folder
        list must stay reachable from a revoked or expired account, which is exactly
        what `usable`'s own gate below would refuse.
        """
        account = self._present(actor)
        if account.status == "expired":
            raise DriveConsentExpired(account.id, account.email_address)
        if account.status != "active":
            raise DriveCredentialRevoked(account.id, account.email_address)
        if scope not in account.scopes_granted:
            # Not a credential problem: `status` stays `active` and every other scope
            # keeps working. It is this feature that is unavailable.
            raise _missing_scope_conflict(scope, feature)
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
        one trying to recover from exactly that state.

        **Choosing the write folder proves it is visible and a folder.** A new,
        non-null `storage_folder_id` is verified against Drive --
        `_verify_storage_folder`, below -- *before* anything on the row changes, so a
        titolare who pastes the wrong id gets `ValidationFailed` naming it and nothing
        is written, rather than discovering the mistake on the CRM's first upload.
        Only existence, visibility and shape are proven this way; whether Drive will
        actually accept a write there has no cheap way to be asked ahead of one.
        `root_folder_ids` are read roots and are never dereferenced here; a Drive
        query against them only ever runs when the reader actually uses one.

        **Only an `active` account is asked to prove anything.** The settings page
        resends the currently configured `storage_folder_id` on *every* save,
        revoked or not -- there is no "unchanged, skip it" on the client. A revoked or
        expired credential has no bearer token behind it that could answer a
        `files.get` truthfully, so verifying over one would not prove the folder is
        wrong; it would only turn every save on a broken account into
        `DriveCredentialRevoked`, discarding the roots change along with it and
        breaking exactly the recovery path the paragraph above describes (fixing the
        folder list from a revoked or expired account). So verification is gated on
        `account.status == "active"`: on any other status the folder is saved
        unverified, same as `root_folder_ids` always are, and is verified for real at
        the next save made after the credential is reconnected and active again.

        **PATCH semantics, and why `model_fields_set` is read here.** The route is a
        `PATCH`: it changes the fields the request named and leaves the rest alone.
        `root_folder_ids` is required, so it is always one of them. `storage_folder_id`
        is not, and on a Pydantic model with a `None` default an omitted field and an
        explicit `null` are *the same value* -- `data.storage_folder_id` cannot tell
        them apart. Writing it unconditionally therefore made a request that only edits
        the read roots erase the write folder, and record `storage_folder_id: None` in
        the timeline as though somebody had asked for that. `model_fields_set` is the
        one place the difference still exists, so it is what decides: named (with an id
        or with `null`) means write it and record it, absent means neither -- and only
        naming a real id, never `null`, on an `active` account, means verify it.
        """
        actor.require_write(_ROOTS_ACTION)
        account = self._present(actor)
        if (
            account.status == "active"
            and "storage_folder_id" in data.model_fields_set
            and data.storage_folder_id is not None
        ):
            # Before any mutation: a failed verification must leave the row and the
            # timeline exactly as they were.
            self._verify_storage_folder(account, data.storage_folder_id)
        account.root_folder_ids = list(data.root_folder_ids)
        payload: dict[str, object] = {"root_folder_ids": list(data.root_folder_ids)}
        if "storage_folder_id" in data.model_fields_set:
            account.storage_folder_id = data.storage_folder_id
            payload["storage_folder_id"] = data.storage_folder_id
        # Last thing before the commit: ActivityService.record flushes and joins this
        # transaction, so nothing may commit after it on this session.
        self.activities.record(
            "google_drive_account",
            account.id,
            "drive.radici_impostate",
            actor,
            payload,
        )
        self.session.commit()
        return GoogleDriveAccountRead.model_validate(account)

    def _verify_storage_folder(self, account: GoogleDriveAccount, folder_id: str) -> None:
        """Proves `folder_id` is visible with `account`'s own credential and is
        itself a folder, before `set_roots` writes it anywhere. Only ever called on an
        `active` account (`set_roots` gates that); everything below assumes it.

        The same call `GDriveStorage.verify_root_accessible` makes for a service
        account's configured root -- a `files.get` for `id,mimeType` -- made here
        instead for the folder a titolare just chose, through their own transport
        (`self._transport_factory`, a real `DriveTransport` in production, a fake one
        in a test). Only existence, visibility and shape are checked: whether Drive
        will actually accept a write there has no cheap way to be asked ahead of one,
        and `verify_root_accessible` settles for exactly this same proof at startup.

        `DRIVE_SCOPE_READONLY` is checked first, and without ever building a
        transport: an `active` account missing it cannot make this call succeed no
        matter what `folder_id` names, and letting the request through to Drive
        anyway would answer with the same 404 a genuinely wrong id gets -- naming the
        *folder* as the problem when the problem is the grant. `_missing_scope_conflict`
        is the same `Conflict` `usable` would raise for the identical scope on the
        identical account, so the two gates read as one rule from either call site.

        A 404 from the call itself means the id names nothing this credential can
        see -- the wrong id, a folder never shared with this account -- and becomes a
        `ValidationFailed` on `storage_folder_id` naming it, the same shape every other
        bad field on this schema fails with. Any other Drive refusal (403, 5xx, a
        broken credential's own 401) is not a bad id and propagates as the `Conflict`
        the transport raised. `DriveCredentialRevoked` is caught ahead of that, because
        it is not `Conflict` as a *symptom of this call* -- it is the same fact
        `mark_revoked` already records everywhere else a refresh answers
        `invalid_grant` -- so it is recorded here too, then re-raised unflattened.
        """
        if DRIVE_SCOPE_READONLY not in account.scopes_granted:
            raise _missing_scope_conflict(DRIVE_SCOPE_READONLY, _FEATURE_VERIFY_STORAGE_FOLDER)
        transport = self._transport_factory(account)
        try:
            meta = transport.json(
                "GET",
                file_meta_url(folder_id, fields="id,mimeType"),
                what=_WHAT_VERIFY_STORAGE_FOLDER,
            )
        except DriveCredentialRevoked:
            self.mark_revoked(
                account, Actor.system(), _REVOKED_TEXT.format(email=account.email_address)
            )
            raise
        except Conflict as failed:
            if (
                failed.details.get("what") == _WHAT_VERIFY_STORAGE_FOLDER
                and failed.details.get("status") == 404
            ):
                raise ValidationFailed(
                    "google_drive_account",
                    "storage_folder_id",
                    f"la cartella {folder_id} non è raggiungibile con questo account "
                    "Google: verifica l'id o condividila con l'account collegato",
                    expected="l'id di una cartella visibile a questo account Google",
                ) from failed
            raise
        if meta.get("mimeType") != FOLDER_MIME:
            raise ValidationFailed(
                "google_drive_account",
                "storage_folder_id",
                f"{folder_id} non è una cartella di Google Drive",
                expected="l'id di una cartella, non di un file",
            )

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
