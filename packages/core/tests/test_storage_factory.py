"""Which credential writes the documents, and when that question gets answered.

Two ways to configure Drive after slice 9: the service account every earlier
installation set up in the environment, and the titolare's *own* connected account
writing into a folder they chose in Impostazioni → Drive. The first is fully known at
startup. The second is not known at startup at all -- the row it lives in may not exist
yet, and the API has to boot anyway, or nobody can reach the settings page that would
create it. So the second one resolves at the first operation instead, and that is the
property most of this file is about.

Nothing here touches the network. Drive is `fakes/fake_drive.py` and Google's token
endpoint is `fakes/fake_gmail.py`, so the composition under test -- unseal the stored
refresh token, exchange it through the slice 5 token client, put the resulting bearer
token on every Drive request -- runs for real, end to end, against a fake of the
network and of nothing else.
"""

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import pytest
from fakes.fake_drive import FOLDER_MIME, FakeDrive
from fakes.fake_gmail import FakeGmail
from fakes.gmail_fixtures import TOKEN_KEY, gmail_settings
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.auth.models import User
from pigrocrm.core.config import Settings
from pigrocrm.core.drive.errors import DriveCredentialRevoked
from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.query import file_meta_url
from pigrocrm.core.drive.repository import DriveRepository
from pigrocrm.core.drive.schemas import DRIVE_SCOPE_FILE, DRIVE_SCOPE_READONLY
from pigrocrm.core.drive.transport import user_transport_for
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed
from pigrocrm.core.gmail.crypto import seal
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport
from pigrocrm.core.storage.errors import StorageNotConfigured
from pigrocrm.core.storage.factory import storage_from_settings
from pigrocrm.core.storage.gdrive import GDriveStorage
from pigrocrm.core.storage.lazy_drive import LazyUserDriveStorage
from pigrocrm.core.storage.local import LocalFileStorage

PDF = b"%PDF-1.7\nfinto\n"
KEY = "acme-01234567/0199abcd/v1.pdf"
OTHER_KEY = "beta-76543210/0199ffff/v1.pdf"
TTL = timedelta(minutes=5)
# Drive file ids of the shape `DriveRootsUpdate` holds a typed-in id to.
STORAGE_FOLDER = "1CartellaScritturaA"
OTHER_FOLDER = "1CartellaScritturaB"
REFRESH_TOKEN = "1//0gDriveStorageRefresh"
MAILBOX = "titolare@example.it"

# No real RSA key is needed: the service-account branch never gets as far as signing
# anything here (its root verification is stubbed), so no private key material exists
# in this repository at all.
SERVICE_ACCOUNT_JSON = (
    '{"type":"service_account","client_email":"pigro@example.iam.gserviceaccount.com",'
    '"private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n",'
    '"token_uri":"https://oauth2.googleapis.com/token"}'
)


@dataclass
class RecordingHttp:
    """Records the headers of every request, then delegates to the real fake.

    `FakeDrive` records `(method, url)` and the parsed query string, deliberately not
    the headers. Wrapping it keeps every bit of its Drive semantics while making the
    one thing this file has to see -- *whose* bearer token reached the wire -- an
    assertion rather than a claim.
    """

    inner: FakeDrive
    headers: list[dict[str, str]] = field(default_factory=list)

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        self.headers.append(dict(headers))
        return self.inner(method, url, headers, body)


def _account(
    session: Session,
    *,
    status: str = "active",
    storage_folder_id: str | None = STORAGE_FOLDER,
    updated_at: datetime | None = None,
) -> GoogleDriveAccount:
    """A connected Drive with a write folder chosen -- the state the lazy storage has
    to find.

    The refresh token is really sealed, with the same key `gmail_settings()` publishes,
    so the unsealing under test runs for real rather than reading a plaintext column
    production never has.
    """
    user = User(
        email=f"drive-{uuid4().hex[:8]}@example.it",
        nome="Titolare",
        password_hash="x",
        ruolo="admin",
        attivo=True,
    )
    session.add(user)
    session.flush()
    ciphertext, nonce = seal(REFRESH_TOKEN, TOKEN_KEY)
    account = GoogleDriveAccount(
        user_id=user.id,
        google_sub=f"sub-{user.id}",
        email_address=MAILBOX,
        refresh_token_ciphertext=ciphertext,
        refresh_token_nonce=nonce,
        scopes_granted=[DRIVE_SCOPE_READONLY, DRIVE_SCOPE_FILE],
        status=status,
        root_folder_ids=[],
        storage_folder_id=storage_folder_id,
    )
    if updated_at is not None:
        account.updated_at = updated_at
    session.add(account)
    session.flush()
    return account


def _sessions(db_session: Session) -> Callable[[], Session]:
    """A `session_factory` the lazy storage may open *and close* freely.

    It cannot be `lambda: db_session`: the storage owns the lifecycle of every session
    it opens (production hands it a `sessionmaker`), and closing the suite's own
    session would end the transaction the `db_session` fixture rolls back at the end of
    the test. Binding a fresh `Session` to the same `Connection` with
    `create_savepoint` gives a genuinely independent session that still sees this
    test's uncommitted rows, and whose own commits -- `mark_revoked` does commit -- nest
    inside the fixture's transaction instead of escaping it.
    """
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def _token_client(gmail: FakeGmail, settings: Settings) -> GoogleTokenClient:
    return GoogleTokenClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        transport=GmailTransport(http=gmail, sleep=lambda _: None),
    )


def _lazy(
    db_session: Session,
    *,
    drive: FakeDrive | RecordingHttp,
    gmail: FakeGmail,
    sessions: Callable[[], Session] | None = None,
) -> LazyUserDriveStorage:
    settings = gmail_settings(storage_backend="gdrive")
    return LazyUserDriveStorage(
        sessions or _sessions(db_session),
        settings,
        http=drive,
        tokens=_token_client(gmail, settings),
    )


def _fail_if_called() -> Session:
    raise AssertionError("nessuna sessione va aperta qui")


# --- storage_from_settings: which of the two Drive routes, decided once --------------


def test_a_configured_service_account_still_gets_the_service_account_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec 5.4: il service account resta supportato per chi lo aveva configurato.

    An installation with both variables set keeps getting exactly what it had -- and in
    particular must not be handed a storage that waits for somebody to connect a Drive
    account it has no need of."""
    monkeypatch.setattr(GDriveStorage, "verify_root_accessible", lambda self: None)
    settings = gmail_settings(
        storage_backend="gdrive",
        gdrive_service_account_json=SERVICE_ACCOUNT_JSON,
        gdrive_root_folder_id="1CartellaRadiceSAX",
    )

    storage = storage_from_settings(settings, session_factory=_fail_if_called)

    assert isinstance(storage, GDriveStorage)
    assert not isinstance(storage, LazyUserDriveStorage)


def test_gdrive_without_a_service_account_and_without_a_session_factory_is_refused() -> None:
    """The user-credential route needs a way to reach the database, because the folder
    it writes into lives in a row. An adapter that selects `gdrive` and hands over no
    session factory has configured neither route -- and the refusal is the one that
    names *both* of them, since that is the choice the reader has to make."""
    settings = gmail_settings(storage_backend="gdrive")

    with pytest.raises(ValidationFailed) as excinfo:
        storage_from_settings(settings)

    reason = excinfo.value.details["reason"]
    assert "PIGROCRM_GDRIVE_SERVICE_ACCOUNT_JSON" in reason
    assert "collega Drive da Impostazioni e scegli la cartella di scrittura" in reason
    # No slice number: an operator reading a startup failure has no map of this
    # project's slices.
    assert "slice" not in reason


def test_a_half_configured_service_account_is_still_a_startup_failure() -> None:
    """The trap this branch exists to avoid: somebody sets the JSON key, forgets the
    root folder id, and -- because a session factory happens to be available -- silently
    gets the *other* credential instead of being told what is missing. Naming either
    service-account variable is a statement of intent, so the other one is then
    required, and the failure is loud."""
    settings = gmail_settings(
        storage_backend="gdrive", gdrive_service_account_json=SERVICE_ACCOUNT_JSON
    )

    with pytest.raises(ValidationFailed):
        storage_from_settings(settings, session_factory=_fail_if_called)


def test_gdrive_with_a_session_factory_returns_a_lazy_storage_and_opens_no_session() -> None:
    """The whole reason this storage is lazy: the API must start before the titolare has
    connected Drive. Construction therefore reads nothing -- proven by a factory that
    fails the test if it is ever called."""
    storage = storage_from_settings(
        gmail_settings(storage_backend="gdrive"), session_factory=_fail_if_called
    )

    assert isinstance(storage, LazyUserDriveStorage)


def test_local_stays_the_default(tmp_path: Path) -> None:
    settings = gmail_settings(storage_local_root=str(tmp_path))
    assert isinstance(storage_from_settings(settings, session_factory=None), LocalFileStorage)


# --- DriveRepository.storage_account: the one row that may be written into -----------


def test_storage_account_finds_the_active_account_that_has_a_write_folder(
    db_session: Session,
) -> None:
    account = _account(db_session)
    assert DriveRepository(db_session).storage_account() is account


def test_storage_account_ignores_an_account_with_no_write_folder(db_session: Session) -> None:
    """Connected is not configured. A Drive whose `storage_folder_id` is still `None`
    can be read from, and writing into it would mean picking a folder somewhere in the
    titolare's personal Drive on their behalf."""
    _account(db_session, storage_folder_id=None)
    assert DriveRepository(db_session).storage_account() is None


@pytest.mark.parametrize("status", ["revoked", "expired", "disconnected"])
def test_storage_account_ignores_an_account_that_is_not_active(
    db_session: Session, status: str
) -> None:
    _account(db_session, status=status)
    assert DriveRepository(db_session).storage_account() is None


def test_storage_account_prefers_the_most_recently_updated_when_more_than_one_qualifies(
    db_session: Session,
) -> None:
    """The installation is single-tenant and the column is unique per *user*, so two
    qualifying rows is not the expected state -- but "not expected" is not
    "impossible": two users can each connect a Drive and each choose a folder. A query
    that raised there would take the whole documents feature down, so the most recently
    configured row wins, because it is the one somebody just chose.
    """
    older = _account(db_session, updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    newer = _account(
        db_session, storage_folder_id=OTHER_FOLDER, updated_at=datetime(2026, 6, 1, tzinfo=UTC)
    )

    found = DriveRepository(db_session).storage_account()

    assert found is newer and found is not older


# --- Not configured: the first operation says so, and says what to do ----------------


def test_the_first_put_without_a_connected_drive_says_how_to_configure_it(
    db_session: Session,
) -> None:
    storage = _lazy(db_session, drive=FakeDrive(), gmail=FakeGmail())

    with pytest.raises(StorageNotConfigured) as excinfo:
        storage.put(KEY, PDF, "application/pdf")

    assert (
        "collega Drive e scegli la cartella di scrittura in Impostazioni → Drive"
        in excinfo.value.details["reason"]
    )


def test_storage_not_configured_is_rendered_as_a_conflict() -> None:
    """`STATUS_BY_CODE` in `apps/api/errors.py` maps `conflict` to 409, and the MCP
    adapter renders the same `details`. This exception therefore needs no new mapping
    anywhere, which is the point of it being a `Conflict`: a state of the installation
    somebody can go and fix, not a malformed request."""
    assert issubclass(StorageNotConfigured, Conflict)
    assert StorageNotConfigured().code == "conflict"


def test_get_without_a_connected_drive_does_not_report_a_missing_document(
    db_session: Session,
) -> None:
    """A `get` that fell through to `NotFound` would tell somebody their document is
    gone when what is missing is the configuration -- and they would go looking for the
    document."""
    storage = _lazy(db_session, drive=FakeDrive(), gmail=FakeGmail())

    with pytest.raises(StorageNotConfigured):
        storage.get(KEY)


def test_delete_without_a_connected_drive_does_not_report_success(db_session: Session) -> None:
    """`delete` is silent for a key that is not there, deliberately (see
    `DocumentStorage`). It must not be silent for a backend that was never configured:
    that would report a deletion nobody performed."""
    storage = _lazy(db_session, drive=FakeDrive(), gmail=FakeGmail())

    with pytest.raises(StorageNotConfigured):
        storage.delete(KEY)


def test_signed_url_without_a_connected_drive_refuses_too(db_session: Session) -> None:
    """`GDriveStorage.signed_url` answers `None` on purpose and never calls Drive, so
    this is the one operation that could plausibly have been allowed through. It is not:
    `None` from a backend that does not exist is indistinguishable from `None` from one
    that does, and the caller would learn nothing."""
    storage = _lazy(db_session, drive=FakeDrive(), gmail=FakeGmail())

    with pytest.raises(StorageNotConfigured):
        storage.signed_url(KEY, TTL)


# --- Configured: the titolare's own credential, the titolare's own folder -------------


def test_put_writes_under_the_chosen_folder_with_the_owners_own_bearer_token(
    db_session: Session,
) -> None:
    """The slice in one test: the bytes land under the folder the titolare picked -- one
    folder per customer beneath it, exactly the arrangement the service account
    produces -- and every request that put them there carried *their* access token,
    obtained by refreshing the sealed refresh token on their row."""
    _account(db_session)
    drive = FakeDrive(root_id=STORAGE_FOLDER)
    gmail = FakeGmail()
    http = RecordingHttp(drive)
    storage = _lazy(db_session, drive=http, gmail=gmail)

    storage.put(KEY, PDF, "application/pdf")

    folders = {f.name: f for f in drive.files.values() if f.mime == FOLDER_MIME}
    assert folders["acme-01234567"].parent == STORAGE_FOLDER
    assert folders["0199abcd"].parent == folders["acme-01234567"].id
    written = [f for f in drive.files.values() if f.name == "v1.pdf"]
    assert [f.data for f in written] == [PDF]
    assert written[0].parent == folders["0199abcd"].id
    assert http.headers  # the put really did make requests
    assert {h["Authorization"] for h in http.headers} == {f"Bearer {gmail.access_token}"}
    # And the token came from Google's token endpoint rather than from the Drive fake's
    # own shortcut: `FakeDrive` answers the token URL too, so a composition that had
    # accidentally kept the service-account provider would still have worked here.
    assert gmail.token_requests == 1
    assert drive.token_requests == 0


def test_get_reads_back_what_put_wrote_and_delete_removes_it(db_session: Session) -> None:
    """Read-your-own-writes, the `DocumentStorage` minimum, through the lazy wrapper --
    which is where it could plausibly break, since every call resolves the account
    again."""
    _account(db_session)
    storage = _lazy(db_session, drive=FakeDrive(root_id=STORAGE_FOLDER), gmail=FakeGmail())

    storage.put(KEY, PDF, "application/pdf")
    assert storage.get(KEY) == PDF

    storage.delete(KEY)
    with pytest.raises(NotFound):
        storage.get(KEY)


def test_the_transport_is_built_once_and_reused_across_operations(db_session: Session) -> None:
    """The resolution is cached, and the cache earns its keep for a reason beyond the
    query it saves: rebuilding the transport would rebuild the `GoogleTokenClient`,
    whose in-memory cache is the only thing between one upload and one OAuth round-trip
    per Drive call. One token request for three operations."""
    _account(db_session)
    gmail = FakeGmail()
    storage = _lazy(db_session, drive=FakeDrive(root_id=STORAGE_FOLDER), gmail=gmail)

    storage.put(KEY, PDF, "application/pdf")
    storage.get(KEY)
    storage.delete(KEY)

    assert gmail.token_requests == 1


def test_changing_the_write_folder_takes_effect_without_a_restart(db_session: Session) -> None:
    """`updated_at` is the seam. The titolare changes the folder in Impostazioni →
    Drive; the next upload has to land in the new one. A storage that resolved once and
    never looked again would keep writing into the old folder until somebody restarted
    the API, with nothing on any screen to say so."""
    account = _account(db_session)
    drive = FakeDrive(root_id=STORAGE_FOLDER)
    storage = _lazy(db_session, drive=drive, gmail=FakeGmail())
    storage.put(KEY, PDF, "application/pdf")

    account.storage_folder_id = OTHER_FOLDER
    account.updated_at = datetime.now(UTC)
    db_session.flush()

    storage.put(OTHER_KEY, b"nuovo", "application/pdf")

    folders = {f.name: f for f in drive.files.values() if f.mime == FOLDER_MIME}
    assert folders["acme-01234567"].parent == STORAGE_FOLDER
    assert folders["beta-76543210"].parent == OTHER_FOLDER


def test_disconnecting_drive_stops_the_writes_at_the_next_operation(
    db_session: Session,
) -> None:
    """The other half of re-resolution: a storage that cached the account forever would
    keep writing into somebody's Drive after they unhooked it."""
    account = _account(db_session)
    storage = _lazy(db_session, drive=FakeDrive(root_id=STORAGE_FOLDER), gmail=FakeGmail())
    storage.put(KEY, PDF, "application/pdf")

    account.status = "disconnected"
    db_session.flush()

    with pytest.raises(StorageNotConfigured):
        storage.put(KEY, PDF, "application/pdf")


# --- A revoked grant: recorded once, where the user can read it ----------------------


def test_a_revoked_grant_is_recorded_on_the_row_and_re_raised(db_session: Session) -> None:
    """A refresh answering `invalid_grant` is something only this code path can learn,
    and the fact has to outlive the request that learned it: the upload is about to fail
    and its transaction to roll back, so `mark_revoked` commits on its own behalf (the
    same contract `gmail/sync.py` relies on). The exception continues afterwards,
    unflattened, so the caller stops rather than carrying on against a dead credential.
    """
    account_id = _account(db_session).id
    storage = _lazy(
        db_session, drive=FakeDrive(root_id=STORAGE_FOLDER), gmail=FakeGmail(revoked=True)
    )

    with pytest.raises(DriveCredentialRevoked):
        storage.put(KEY, PDF, "application/pdf")

    db_session.expire_all()
    stored = db_session.get(GoogleDriveAccount, account_id)
    assert stored is not None
    assert stored.status == "revoked"
    assert stored.last_error is not None
    assert MAILBOX in stored.last_error
    assert REFRESH_TOKEN not in stored.last_error
    kinds = db_session.execute(select(Activity.kind)).scalars().all()
    assert "drive.credenziale_revocata" in kinds


def test_after_a_revocation_the_next_operation_asks_for_configuration_again(
    db_session: Session,
) -> None:
    """`mark_revoked` moves the row off `active`, so it stops being the account that may
    be written into -- and the next attempt says what to do about it rather than raising
    the same revocation forever out of a cached transport."""
    _account(db_session)
    storage = _lazy(
        db_session, drive=FakeDrive(root_id=STORAGE_FOLDER), gmail=FakeGmail(revoked=True)
    )
    with pytest.raises(DriveCredentialRevoked):
        storage.put(KEY, PDF, "application/pdf")

    with pytest.raises(StorageNotConfigured):
        storage.put(KEY, PDF, "application/pdf")


def test_a_failed_revocation_record_never_hides_the_revocation_itself(
    db_session: Session,
) -> None:
    """The bookkeeping is best effort; the failure it describes is not.

    Recording the revocation needs a second session, and everything about that second
    session can fail on its own -- a pool that has no connection left, a row somebody
    else is holding, a `commit` that loses a race. Left unguarded, any of those replaces
    `DriveCredentialRevoked` with a SQLAlchemy error: the caller then sees an internal
    failure instead of "il consenso è stato revocato", the API renders a 500 rather than
    a 409, and the row it was trying to mark is still `active` anyway -- so the reader
    loses both the sentence and the record.

    The accepted consequence is asserted too: the row *stays* `active`. That is honest
    about what a swallowed exception costs. The next refresh will meet the same
    `invalid_grant` and try to record it again, which is exactly the retry a database
    that was momentarily unavailable needs -- and it is a far better failure mode than a
    revocation reported as an outage.
    """
    account_id = _account(db_session).id
    working = _sessions(db_session)
    opened = 0

    def sessions() -> Session:
        nonlocal opened
        opened += 1
        if opened == 2:  # 1 is the resolution, 2 is the revocation record
            raise RuntimeError("nessuna connessione disponibile nel pool")
        return working()

    storage = _lazy(
        db_session,
        drive=FakeDrive(root_id=STORAGE_FOLDER),
        gmail=FakeGmail(revoked=True),
        sessions=sessions,
    )

    with pytest.raises(DriveCredentialRevoked):
        storage.put(KEY, PDF, "application/pdf")

    assert opened == 2  # the record really was attempted, and really did fail
    db_session.expire_all()
    stored = db_session.get(GoogleDriveAccount, account_id)
    assert stored is not None and stored.status == "active"


# --- user_transport_for: the token composition, written once --------------------------


def test_user_transport_for_unseals_the_stored_token_and_refreshes_it_as_the_user(
    db_session: Session,
) -> None:
    """One helper composes a Drive transport from a stored account, and these are the
    three steps it has to get right: the ciphertext columns are unsealed with the
    installation's key, the plaintext refresh token is what gets posted to Google's
    token endpoint, and the access token that comes back is what every Drive request
    carries.

    A module-level helper because the Drive *reader* needs the identical three steps,
    and a second copy of them would be a second place a refresh token is handled.
    """
    account = _account(db_session)
    http = RecordingHttp(FakeDrive(root_id=STORAGE_FOLDER))
    gmail = FakeGmail()
    settings = gmail_settings()

    transport = user_transport_for(
        account, settings, http=http, tokens=_token_client(gmail, settings)
    )
    transport.json("GET", file_meta_url(STORAGE_FOLDER, fields="id"), what="la cartella")

    assert [h["Authorization"] for h in http.headers] == [f"Bearer {gmail.access_token}"]
    posted = parse_qs((gmail.requests[-1].body or b"").decode())
    assert posted["refresh_token"] == [REFRESH_TOKEN]
    assert posted["grant_type"] == ["refresh_token"]


def test_user_transport_for_reports_a_wrong_key_as_a_credential_problem(
    db_session: Session,
) -> None:
    """`unseal` refuses before anything is composed, and names the environment variable
    rather than the ciphertext. Asserted here because the storage path is the one most
    likely to meet a rotated `PIGROCRM_GOOGLE_TOKEN_KEY` first."""
    account = _account(db_session)
    wrong_key = gmail_settings(google_token_key=base64.b64encode(b"z" * 32).decode())

    with pytest.raises(Conflict) as excinfo:
        user_transport_for(account, wrong_key)

    assert "PIGROCRM_GOOGLE_TOKEN_KEY" in excinfo.value.details["reason"]
