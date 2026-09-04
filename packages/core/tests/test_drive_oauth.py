"""The Drive credential: a second grant, a second row, the same key (spec 9 §5)."""

import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fakes.fake_gmail import FakeGmail
from fakes.gmail_fixtures import TOKEN_KEY, gmail_settings
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.activities.models import Activity
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.drive.account import CONSENT_WARNING_HOURS, GoogleDriveAccountService
from pigrocrm.core.drive.errors import DriveConsentExpired, DriveCredentialRevoked
from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.oauth import GoogleDriveOAuthService
from pigrocrm.core.drive.schemas import (
    DRIVE_REQUESTED_SCOPES,
    DRIVE_SCOPE_FILE,
    DRIVE_SCOPE_READONLY,
    DriveRootsUpdate,
    GoogleDriveAccountRead,
)
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.crypto import seal, unseal
from pigrocrm.core.gmail.errors import ConsentExpired, CredentialRevoked
from pigrocrm.core.gmail.models import GoogleAccount, GoogleOAuthState
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import MAX_HTTP_ATTEMPTS, GmailTransport


@pytest.fixture
def admin_user(db_session: Session) -> User:
    # No `admin_user` fixture exists in conftest.py; built inline the same way
    # `test_auth_session_ttl.py::admin_user` does, since all this test needs is a
    # persisted user row for the foreign keys below.
    user = User(
        email=f"drive-{uuid4().hex[:8]}@example.it",
        nome="Owner",
        password_hash="x",
        ruolo="admin",
        attivo=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_the_requested_scopes_are_exactly_the_four_of_the_spec() -> None:
    assert DRIVE_REQUESTED_SCOPES == (
        "openid",
        "email",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
    )


def test_a_drive_account_row_round_trips_and_hides_its_token(
    db_session: Session, admin_user: User
) -> None:
    row = GoogleDriveAccount(
        user_id=admin_user.id,
        google_sub="sub-1",
        email_address="io@example.it",
        refresh_token_ciphertext=b"\x01",
        refresh_token_nonce=b"\x02",
        scopes_granted=list(DRIVE_REQUESTED_SCOPES),
        status="active",
        root_folder_ids=["1AbCdEfGhIjKlMnOpQ"],
        storage_folder_id=None,
    )
    db_session.add(row)
    db_session.flush()
    read = GoogleDriveAccountRead.model_validate(row)
    assert read.root_folder_ids == ["1AbCdEfGhIjKlMnOpQ"]
    assert "refresh_token" not in read.model_dump_json()


def test_an_oauth_state_knows_its_purpose(db_session: Session, admin_user: User) -> None:
    state = GoogleOAuthState(
        jti="j1", code_verifier="v" * 43, user_id=admin_user.id, expires_at=datetime.now(UTC)
    )
    db_session.add(state)
    db_session.flush()
    assert state.purpose == "gmail"


def test_root_ids_are_drive_ids_not_free_text() -> None:
    DriveRootsUpdate(root_folder_ids=["1AbCdEfGhIjKlMnOpQ"])
    with pytest.raises(ValidationError):
        DriveRootsUpdate(root_folder_ids=["'x' in parents or name contains 'a'"])
    with pytest.raises(ValidationError):
        DriveRootsUpdate(root_folder_ids=[])


# --- the OAuth flow (spec 9 §5.1-5.2) --------------------------------------------------


def _id_token(sub: str, email: str) -> str:
    """Copied verbatim from `test_gmail_oauth.py`: a real JWT is not needed, only the
    unverified payload `_decode_id_token_claims` reads."""
    claims = base64.urlsafe_b64encode(json.dumps({"sub": sub, "email": email}).encode())
    return f"header.{claims.decode().rstrip('=')}.signature"


def _drive_fake(sub: str, email: str) -> FakeGmail:
    fake = FakeGmail(granted_scopes=DRIVE_REQUESTED_SCOPES)  # type: ignore[arg-type]
    fake.id_token = _id_token(sub, email)
    fake.refresh_token = "1//0gDriveRefresh"
    fake.access_token = "ya29.drive-access-token"
    return fake


def _drive_service(session: Session, fake: FakeGmail) -> GoogleDriveOAuthService:
    settings = gmail_settings()
    transport = GmailTransport(http=fake, sleep=lambda _: None)
    return GoogleDriveOAuthService(
        session,
        settings=settings,
        tokens=GoogleTokenClient(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            transport=transport,
        ),
    )


def _actor(user: User) -> Actor:
    return Actor(id=user.id, type="user", role="admin")  # type: ignore[arg-type]


def _connected_gmail_account(
    session: Session, user: User, *, google_sub: str, email_address: str = "mailbox@example.it"
) -> GoogleAccount:
    """A Gmail account of this CRM user, built directly rather than through
    `fakes.gmail_fixtures.connected_account` -- that helper mints its own user, and
    this test needs the mailbox to belong to the very user starting the Drive flow.
    """
    ciphertext, nonce = seal("1//0gMailboxRefresh", TOKEN_KEY)
    account = GoogleAccount(
        user_id=user.id,
        google_sub=google_sub,
        email_address=email_address,
        refresh_token_ciphertext=ciphertext,
        refresh_token_nonce=nonce,
        scopes_granted=[],
        status="active",
    )
    session.add(account)
    session.flush()
    return account


def test_start_asks_google_for_drive_scopes_only_with_pkce(
    db_session: Session, admin_user: User
) -> None:
    service = _drive_service(db_session, FakeGmail())
    url = service.start(_actor(admin_user))
    q = parse_qs(urlparse(url).query)

    assert q["scope"] == [" ".join(DRIVE_REQUESTED_SCOPES)]
    assert q["redirect_uri"][0].endswith("/api/drive/oauth/callback")
    assert q["code_challenge_method"] == ["S256"]
    assert q["access_type"] == ["offline"]
    state = db_session.execute(
        select(GoogleOAuthState).where(GoogleOAuthState.jti == q["state"][0])
    ).scalar_one()
    assert state.purpose == "drive"


def test_complete_stores_a_sealed_token_and_refuses_a_foreign_sub(
    db_session: Session, admin_user: User
) -> None:
    """The Gmail account of this user is `sub-gmail`; a Drive grant for another Google
    identity is refused, a grant for the same identity is stored, sealed, with no
    CRM-imposed expiry."""
    _connected_gmail_account(db_session, admin_user, google_sub="sub-gmail")

    fake = _drive_fake("sub-other", "other@gmail.com")
    service = _drive_service(db_session, fake)
    url = service.start(_actor(admin_user))
    jti = parse_qs(urlparse(url).query)["state"][0]

    with pytest.raises(Conflict) as caught:
        service.complete(code="c", state=jti, actor=_actor(admin_user))
    assert "mailbox@example.it" in caught.value.message
    assert (
        db_session.execute(
            select(GoogleDriveAccount).where(GoogleDriveAccount.user_id == admin_user.id)
        )
        .scalars()
        .all()
        == []
    )

    fake.id_token = _id_token("sub-gmail", "same@identity.it")
    url2 = service.start(_actor(admin_user))
    jti2 = parse_qs(urlparse(url2).query)["state"][0]

    read = service.complete(code="c2", state=jti2, actor=_actor(admin_user))

    assert read.status == "active"
    assert read.consent_expires_at is None
    row = db_session.execute(
        select(GoogleDriveAccount).where(GoogleDriveAccount.user_id == admin_user.id)
    ).scalar_one()
    assert unseal(row.refresh_token_ciphertext, row.refresh_token_nonce, TOKEN_KEY) == (
        fake.refresh_token
    )
    kinds = db_session.execute(select(Activity.kind)).scalars().all()
    assert "drive.account_collegato" in kinds


def _complete_drive(
    service: GoogleDriveOAuthService, actor: Actor, code: str
) -> GoogleDriveAccountRead:
    url = service.start(actor)
    jti = parse_qs(urlparse(url).query)["state"][0]
    return service.complete(code=code, state=jti, actor=actor)


def _drive_row(session: Session, user: User) -> GoogleDriveAccount:
    return session.execute(
        select(GoogleDriveAccount).where(GoogleDriveAccount.user_id == user.id)
    ).scalar_one()


def test_a_failed_code_exchange_is_reported_as_a_drive_failure_not_a_gmail_one(
    db_session: Session, admin_user: User
) -> None:
    """`exchange_code` belongs to the `GoogleTokenClient` the Gmail side owns, and its
    two failure exits name Gmail: `CredentialRevoked` reads "ricollega la casella da
    Impostazioni → Gmail" under the entity `google_account`, and `GmailUnavailable`
    reads "Gmail non ha risposto correttamente". The router turns either into
    `?esito=errore` and the settings page shows the true state, so the browser flow is
    unharmed -- but the same `Conflict` reaches the problem document and the MCP
    message verbatim for anybody who calls `complete` directly, and there it would send
    a person to reconnect a mailbox, or to wait for Gmail, over a *Drive* consent.

    Both halves are checked here because the distinction between them is the whole
    point: terminal and cured by re-consenting, versus transient and cured by waiting.
    """
    revoked_fake = _drive_fake("sub-drive", "drive@example.it")
    revoked_fake.revoked = True
    with pytest.raises(DriveCredentialRevoked) as caught:
        _complete_drive(_drive_service(db_session, revoked_fake), _actor(admin_user), "c1")

    assert not isinstance(caught.value, CredentialRevoked)
    assert "Impostazioni → Drive" in caught.value.details["reason"]
    assert "Gmail" not in caught.value.message and "casella" not in caught.value.message

    down_fake = _drive_fake("sub-drive", "drive@example.it")
    down_fake.fail_with = [(503, b"{}", {})] * MAX_HTTP_ATTEMPTS
    with pytest.raises(Conflict) as unavailable:
        _complete_drive(_drive_service(db_session, down_fake), _actor(admin_user), "c2")

    assert not isinstance(unavailable.value, DriveCredentialRevoked)
    assert unavailable.value.details["entity"] == "google_drive"
    assert "Google Drive" in unavailable.value.details["reason"]
    assert "Gmail" not in unavailable.value.details["reason"]
    # Neither failure may leave a half-built credential behind.
    assert (
        db_session.execute(
            select(GoogleDriveAccount).where(GoogleDriveAccount.user_id == admin_user.id)
        )
        .scalars()
        .all()
        == []
    )


def test_reconnecting_a_different_identity_while_still_connected_is_refused(
    db_session: Session, admin_user: User
) -> None:
    """The Drive twin of `test_reconnecting_a_different_mailbox_is_refused_and_names_both`
    in `test_gmail_oauth.py`: a *connected* row must not be silently overwritten by a
    different Google identity, or a folder configuration built for one account would
    start being read from (and written into) under somebody else's."""
    fake = _drive_fake("sub-a", "a@identity.it")
    service = _drive_service(db_session, fake)
    _complete_drive(service, _actor(admin_user), code="c1")

    fake.id_token = _id_token("sub-b", "b@identity.it")
    with pytest.raises(Conflict) as caught:
        _complete_drive(service, _actor(admin_user), code="c2")

    assert "a@identity.it" in caught.value.message
    assert _drive_row(db_session, admin_user).email_address == "a@identity.it"


def test_reconnecting_a_different_identity_after_disconnect_clears_the_folders(
    db_session: Session, admin_user: User
) -> None:
    """Once the row is disconnected the identity is free to change (the refusal above
    tells the user to disconnect first), but the folders configured for the identity
    that just left have no meaning for the one that replaces it."""
    fake = _drive_fake("sub-a", "a@identity.it")
    service = _drive_service(db_session, fake)
    _complete_drive(service, _actor(admin_user), code="c1")
    row = _drive_row(db_session, admin_user)
    row.root_folder_ids = ["1AbCdEfGhIjKlMnOpQ"]
    row.storage_folder_id = "1AbCdEfGhIjKlMnOpQ"
    db_session.flush()
    service.disconnect(_actor(admin_user))

    fake.id_token = _id_token("sub-b", "b@identity.it")
    read = _complete_drive(service, _actor(admin_user), code="c2")

    assert read.email_address == "b@identity.it"
    assert read.root_folder_ids == []
    assert read.storage_folder_id is None


def test_reconnecting_the_same_identity_after_disconnect_keeps_the_folders(
    db_session: Session, admin_user: User
) -> None:
    """The other half of the rule above: the same identity reconnecting is the
    documented cure for a revoked or expired consent, and it must not throw away a
    folder configuration that still describes the right Drive."""
    fake = _drive_fake("sub-a", "a@identity.it")
    service = _drive_service(db_session, fake)
    _complete_drive(service, _actor(admin_user), code="c1")
    row = _drive_row(db_session, admin_user)
    row.root_folder_ids = ["1AbCdEfGhIjKlMnOpQ"]
    row.storage_folder_id = "1AbCdEfGhIjKlMnOpQ"
    db_session.flush()
    service.disconnect(_actor(admin_user))

    fake.refresh_token = "1//0gDriveRenewedRefresh"
    read = _complete_drive(service, _actor(admin_user), code="c2")

    assert read.root_folder_ids == ["1AbCdEfGhIjKlMnOpQ"]
    assert read.storage_folder_id == "1AbCdEfGhIjKlMnOpQ"


def test_disconnect_forgets_the_cached_token_and_erases_the_credential(
    db_session: Session, admin_user: User
) -> None:
    fake = _drive_fake("sub-a", "a@identity.it")
    service = _drive_service(db_session, fake)
    read = _complete_drive(service, _actor(admin_user), code="c1")
    # Primed the way a real read of the Drive API would, so `disconnect` actually has
    # a cached access token to forget.
    service.tokens.access_token(
        account_id=read.id, email_address=read.email_address, refresh_token=fake.refresh_token
    )
    assert read.id in service.tokens._cache

    service.disconnect(_actor(admin_user))

    assert read.id not in service.tokens._cache
    row = _drive_row(db_session, admin_user)
    assert row.status == "disconnected"
    assert row.disconnected_at is not None
    # Overwritten, not merely dereferenced -- the same rule `GoogleAccount`'s own
    # disconnect follows, and for the same reason: leaving the ciphertext behind
    # means the credential is still in every backup taken after the disconnect.
    assert row.refresh_token_ciphertext == b""
    assert row.refresh_token_nonce == b""
    kinds = db_session.execute(select(Activity.kind)).scalars().all()
    assert "drive.account_scollegato" in kinds


def test_a_gmail_state_cannot_complete_the_drive_flow(
    db_session: Session, admin_user: User
) -> None:
    """`consume_state`'s `purpose` filter, exercised end to end: a state minted by the
    Gmail flow is unknown to the Drive one, and vice versa -- the callback of one flow
    cannot be replayed as if it belonged to the other."""
    gmail_repo = GmailRepository(db_session)
    gmail_jti = "a-gmail-state"
    gmail_repo.add_state(
        GoogleOAuthState(
            jti=gmail_jti,
            code_verifier="v" * 43,
            user_id=admin_user.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    db_session.commit()
    service = _drive_service(db_session, _drive_fake("sub-gmail", "mailbox@example.it"))

    with pytest.raises(Conflict):
        service.complete(code="c", state=gmail_jti, actor=_actor(admin_user))
    assert (
        db_session.execute(
            select(GoogleDriveAccount).where(GoogleDriveAccount.user_id == admin_user.id)
        )
        .scalars()
        .all()
        == []
    )
    # The state was never touched by the Drive flow: it is still there, unconsumed,
    # ready for the Gmail callback it was actually minted for.
    row = db_session.execute(
        select(GoogleOAuthState).where(GoogleOAuthState.jti == gmail_jti)
    ).scalar_one()
    assert row.consumed_at is None


# --- GoogleDriveAccountService: health, the gate, and the configured roots -----------


def _drive_service_account(session: Session) -> GoogleDriveAccountService:
    return GoogleDriveAccountService(session, settings=gmail_settings())


def _drive_actor(user: User) -> Actor:
    return Actor(id=user.id, type="user", role="admin")


def _connected_drive_account(
    session: Session,
    user: User,
    *,
    email_address: str = "io@example.it",
    scopes: tuple[str, ...] = DRIVE_REQUESTED_SCOPES,
    status: str = "active",
) -> GoogleDriveAccount:
    """A Drive row built directly, the way `test_gmail_degradation.py`'s
    `connected_account` builds a Gmail one -- these tests are about the service's own
    logic, not the OAuth round trip `test_complete_stores_a_sealed_token...` above
    already exercises."""
    ciphertext, nonce = seal("1//0gDriveRefresh", TOKEN_KEY)
    account = GoogleDriveAccount(
        user_id=user.id,
        google_sub="sub-1",
        email_address=email_address,
        refresh_token_ciphertext=ciphertext,
        refresh_token_nonce=nonce,
        scopes_granted=list(scopes),
        status=status,
        root_folder_ids=[],
        storage_folder_id=None,
    )
    session.add(account)
    session.flush()
    return account


def test_health_on_an_installation_with_no_drive_account_is_empty_not_an_error(
    db_session: Session, admin_user: User
) -> None:
    """An installation that never connected Drive has nothing to say about it -- a
    banner there would be an error message for a feature nobody switched on."""
    health = _drive_service_account(db_session).health(_drive_actor(admin_user))
    assert health.account is None
    assert health.banner is None
    assert health.missing_scopes == []
    assert health.configured is True


def test_health_on_a_revoked_drive_account_shows_the_revoked_banner(
    db_session: Session, admin_user: User
) -> None:
    account = _connected_drive_account(db_session, admin_user, status="revoked")
    health = _drive_service_account(db_session).health(_drive_actor(admin_user))
    assert health.banner == "revoked"
    assert "revocato" in (health.banner_text or "")
    assert account.email_address in (health.banner_text or "")


def test_health_on_a_disconnected_drive_account_shows_no_banner(
    db_session: Session, admin_user: User
) -> None:
    """Nothing is wrong: the user unhooked Drive on purpose. The account is still
    returned -- the settings page needs to show *something* was connected -- only the
    banner is silent, the same treatment `test_gmail_degradation.py`'s
    `test_a_mailbox_the_user_disconnected_shows_no_banner` gives Gmail."""
    account = _connected_drive_account(db_session, admin_user, status="disconnected")
    health = _drive_service_account(db_session).health(_drive_actor(admin_user))
    assert health.banner is None
    assert health.banner_text is None
    assert health.account is not None
    assert health.account.status == "disconnected"
    assert health.account.email_address == account.email_address


def test_health_on_an_expired_drive_account_shows_the_expired_banner(
    db_session: Session, admin_user: User
) -> None:
    account = _connected_drive_account(db_session, admin_user, status="expired")
    health = _drive_service_account(db_session).health(_drive_actor(admin_user))
    assert health.banner == "expired"
    assert "scaduto" in (health.banner_text or "")
    assert account.email_address in (health.banner_text or "")


def test_health_reports_a_consent_already_past_its_date_as_expired_not_expiring(
    db_session: Session, admin_user: User
) -> None:
    """The window is "within 48 hours", and a date already in the past is inside it by
    arithmetic -- it must not read as a gentle heads-up about the future. The Drive
    twin of `test_gmail_degradation.py`'s
    `test_a_consent_already_past_its_date_is_not_reported_as_merely_expiring`."""
    account = _connected_drive_account(db_session, admin_user)
    account.consent_expires_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.flush()

    health = _drive_service_account(db_session).health(_drive_actor(admin_user))

    assert health.banner == "expired"
    assert "scaduto" in (health.banner_text or "")


def test_health_within_the_warning_window_shows_the_expiring_banner_with_the_date(
    db_session: Session, admin_user: User
) -> None:
    account = _connected_drive_account(db_session, admin_user)
    when = datetime.now(UTC) + timedelta(hours=24)
    account.consent_expires_at = when
    db_session.flush()

    health = _drive_service_account(db_session).health(_drive_actor(admin_user))

    assert health.banner == "expiring"
    assert when.strftime("%d/%m/%Y") in (health.banner_text or "")
    assert CONSENT_WARNING_HOURS == 48


def test_health_missing_readonly_raises_the_scope_missing_banner(
    db_session: Session, admin_user: User
) -> None:
    """The read scope gates the banner; the write scope alone does not -- a Drive
    grant missing only `drive.file` can still read every configured root."""
    account = _connected_drive_account(
        db_session, admin_user, scopes=("openid", "email", DRIVE_SCOPE_READONLY)
    )
    db_session.flush()
    health = _drive_service_account(db_session).health(_drive_actor(admin_user))

    assert health.banner is None
    assert health.missing_scopes == [DRIVE_SCOPE_FILE]

    account.scopes_granted = ["openid", "email", DRIVE_SCOPE_FILE]
    db_session.flush()
    health2 = _drive_service_account(db_session).health(_drive_actor(admin_user))

    assert health2.banner == "scope_missing"
    assert DRIVE_SCOPE_READONLY in (health2.banner_text or "")
    assert health2.missing_scopes == [DRIVE_SCOPE_READONLY]


def test_usable_on_a_revoked_account_raises_credential_revoked(
    db_session: Session, admin_user: User
) -> None:
    """`DriveCredentialRevoked`, not Gmail's `CredentialRevoked`: that one reads
    "ricollega la casella da Impostazioni → Gmail" under the entity `google_account`,
    and it reaches the problem document and the MCP message verbatim -- so a revoked
    *Drive* grant would send somebody to reconnect their mailbox, which fixes nothing
    and hides what actually broke. The distinction the exception carries (terminal,
    cured by re-consenting) is unchanged; only the credential it names is."""
    account = _connected_drive_account(db_session, admin_user, status="revoked")
    with pytest.raises(DriveCredentialRevoked) as caught:
        _drive_service_account(db_session).usable(
            _drive_actor(admin_user), scope=DRIVE_SCOPE_READONLY, feature="la lettura dei documenti"
        )
    assert "revocato" in caught.value.message
    assert not isinstance(caught.value, CredentialRevoked)
    details = caught.value.details
    assert details["entity"] == "google_drive_account"
    assert "Impostazioni → Drive" in details["reason"]
    assert "Gmail" not in details["reason"] and "casella" not in details["reason"]
    assert details["account_id"] == str(account.id)
    assert details["email_address"] == account.email_address
    # The row's own token bytes are the one thing this exception may never carry.
    assert "ciphertext" not in str(details) and "nonce" not in str(details)


def test_usable_on_an_expired_account_raises_consent_expired(
    db_session: Session, admin_user: User
) -> None:
    """Same substitution, the predicted half: `DriveConsentExpired` rather than Gmail's
    `ConsentExpired`, whose sentence names the mailbox."""
    account = _connected_drive_account(db_session, admin_user, status="expired")
    with pytest.raises(DriveConsentExpired) as caught:
        _drive_service_account(db_session).usable(
            _drive_actor(admin_user), scope=DRIVE_SCOPE_READONLY, feature="la lettura dei documenti"
        )
    assert "scaduto" in caught.value.message
    assert "revocato" not in caught.value.message
    assert not isinstance(caught.value, ConsentExpired)
    details = caught.value.details
    assert details["entity"] == "google_drive_account"
    assert "Impostazioni → Drive" in details["reason"]
    assert "Gmail" not in details["reason"] and "casella" not in details["reason"]
    assert details["account_id"] == str(account.id)
    assert details["email_address"] == account.email_address


def test_usable_without_a_drive_account_refuses_naming_impostazioni_drive(
    db_session: Session, admin_user: User
) -> None:
    with pytest.raises(Conflict, match="Impostazioni → Drive") as caught:
        _drive_service_account(db_session).usable(
            _drive_actor(admin_user), scope=DRIVE_SCOPE_READONLY, feature="la lettura dei documenti"
        )
    assert not isinstance(caught.value, DriveCredentialRevoked)


def test_usable_on_a_disconnected_account_refuses_the_same_way_as_no_account(
    db_session: Session, admin_user: User
) -> None:
    """A Drive the user unhooked on purpose is folded into the same refusal as "no row
    at all" by `_present`: there is nothing left to gate a use of. It must not read as
    `DriveCredentialRevoked` -- that would be a lie about the user's own action."""
    _connected_drive_account(db_session, admin_user, status="disconnected")
    with pytest.raises(Conflict, match="Impostazioni → Drive") as caught:
        _drive_service_account(db_session).usable(
            _drive_actor(admin_user), scope=DRIVE_SCOPE_READONLY, feature="la lettura dei documenti"
        )
    assert not isinstance(caught.value, DriveCredentialRevoked)


def test_usable_missing_the_requested_scope_names_it_and_leaves_the_account_active(
    db_session: Session, admin_user: User
) -> None:
    account = _connected_drive_account(
        db_session, admin_user, scopes=("openid", "email", DRIVE_SCOPE_FILE)
    )
    db_session.flush()
    service = _drive_service_account(db_session)

    assert (
        service.usable(
            _drive_actor(admin_user), scope=DRIVE_SCOPE_FILE, feature="la scrittura dei documenti"
        ).id
        == account.id
    )
    with pytest.raises(Conflict) as caught:
        service.usable(
            _drive_actor(admin_user), scope=DRIVE_SCOPE_READONLY, feature="la lettura dei documenti"
        )
    assert DRIVE_SCOPE_READONLY in caught.value.message
    assert not isinstance(caught.value, DriveCredentialRevoked)
    db_session.refresh(account)
    assert account.status == "active"


def test_mark_revoked_sets_the_status_and_records_the_activity(
    db_session: Session, admin_user: User
) -> None:
    account = _connected_drive_account(db_session, admin_user)
    service = _drive_service_account(db_session)

    service.mark_revoked(account, Actor.system(), "il consenso Google Drive è stato revocato")

    db_session.refresh(account)
    assert account.status == "revoked"
    assert account.last_error is not None
    assert account.last_error_at is not None
    rows = (
        db_session.execute(select(Activity).where(Activity.kind == "drive.credenziale_revocata"))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].actor_type == "system"
    assert rows[0].entity_type == "google_drive_account"
    assert rows[0].entity_id == account.id


def test_set_roots_persists_both_fields_and_records_the_activity(
    db_session: Session, admin_user: User
) -> None:
    account = _connected_drive_account(db_session, admin_user)
    service = _drive_service_account(db_session)

    read = service.set_roots(
        DriveRootsUpdate(
            root_folder_ids=["1AbCdEfGhIjKlMnOpQ", "2AbCdEfGhIjKlMnOpQ"],
            storage_folder_id="3AbCdEfGhIjKlMnOpQ",
        ),
        _drive_actor(admin_user),
    )

    assert read.root_folder_ids == ["1AbCdEfGhIjKlMnOpQ", "2AbCdEfGhIjKlMnOpQ"]
    assert read.storage_folder_id == "3AbCdEfGhIjKlMnOpQ"
    db_session.refresh(account)
    assert account.root_folder_ids == ["1AbCdEfGhIjKlMnOpQ", "2AbCdEfGhIjKlMnOpQ"]
    assert account.storage_folder_id == "3AbCdEfGhIjKlMnOpQ"
    rows = (
        db_session.execute(select(Activity).where(Activity.kind == "drive.radici_impostate"))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].payload["root_folder_ids"] == ["1AbCdEfGhIjKlMnOpQ", "2AbCdEfGhIjKlMnOpQ"]
    assert rows[0].payload["storage_folder_id"] == "3AbCdEfGhIjKlMnOpQ"


def test_a_patch_that_omits_the_storage_folder_keeps_it_and_leaves_it_out_of_the_timeline(
    db_session: Session, admin_user: User
) -> None:
    """`PATCH` semantics, and the reason `DriveRootsUpdate.storage_folder_id` has to be
    read through `model_fields_set` rather than off the model: absent and explicit
    `null` are the same value on a Pydantic model with a `None` default, so writing it
    unconditionally makes a request that only changes the read roots erase the write
    folder -- and record `storage_folder_id: None` in the timeline as though somebody
    had asked for that.
    """
    account = _connected_drive_account(db_session, admin_user)
    service = _drive_service_account(db_session)
    service.set_roots(
        DriveRootsUpdate(
            root_folder_ids=["1AbCdEfGhIjKlMnOpQ"], storage_folder_id="3AbCdEfGhIjKlMnOpQ"
        ),
        _drive_actor(admin_user),
    )

    read = service.set_roots(
        DriveRootsUpdate(root_folder_ids=["2AbCdEfGhIjKlMnOpQ"]), _drive_actor(admin_user)
    )

    assert read.storage_folder_id == "3AbCdEfGhIjKlMnOpQ"
    db_session.refresh(account)
    assert account.storage_folder_id == "3AbCdEfGhIjKlMnOpQ"
    payloads = [
        row.payload
        for row in db_session.execute(
            select(Activity).where(Activity.kind == "drive.radici_impostate")
        )
        .scalars()
        .all()
    ]
    # Matched by their own `root_folder_ids`, not by row order: two activities recorded
    # in one test can share an `occurred_at` to the microsecond.
    assert len(payloads) == 2
    first = [p for p in payloads if p["root_folder_ids"] == ["1AbCdEfGhIjKlMnOpQ"]]
    second = [p for p in payloads if p["root_folder_ids"] == ["2AbCdEfGhIjKlMnOpQ"]]
    assert len(first) == 1 and len(second) == 1
    assert first[0]["storage_folder_id"] == "3AbCdEfGhIjKlMnOpQ"
    assert "storage_folder_id" not in second[0]


def test_an_explicit_null_storage_folder_clears_it(db_session: Session, admin_user: User) -> None:
    """The other half of the same distinction: `null` was named, so it is written --
    clearing the write folder is a thing a person is allowed to ask for, and the
    timeline records that they did."""
    account = _connected_drive_account(db_session, admin_user)
    service = _drive_service_account(db_session)
    service.set_roots(
        DriveRootsUpdate(
            root_folder_ids=["1AbCdEfGhIjKlMnOpQ"], storage_folder_id="3AbCdEfGhIjKlMnOpQ"
        ),
        _drive_actor(admin_user),
    )

    read = service.set_roots(
        DriveRootsUpdate(root_folder_ids=["2AbCdEfGhIjKlMnOpQ"], storage_folder_id=None),
        _drive_actor(admin_user),
    )

    assert read.storage_folder_id is None
    db_session.refresh(account)
    assert account.storage_folder_id is None
    cleared = [
        row.payload
        for row in db_session.execute(
            select(Activity).where(Activity.kind == "drive.radici_impostate")
        )
        .scalars()
        .all()
        if row.payload["root_folder_ids"] == ["2AbCdEfGhIjKlMnOpQ"]
    ]
    assert len(cleared) == 1
    assert cleared[0]["storage_folder_id"] is None


def test_set_roots_admits_a_revoked_or_expired_account(
    db_session: Session, admin_user: User
) -> None:
    """Fixing the folder list is not a use of the credential, unlike `usable`'s gate:
    the person most likely to be looking at this screen is the one trying to recover
    from exactly one of these two states, so both are let through."""
    service = _drive_service_account(db_session)
    for status in ("revoked", "expired"):
        account = _connected_drive_account(
            db_session, admin_user, email_address=f"{status}@example.it", status=status
        )
        read = service.set_roots(
            DriveRootsUpdate(root_folder_ids=["1AbCdEfGhIjKlMnOpQ"]), _drive_actor(admin_user)
        )
        assert read.root_folder_ids == ["1AbCdEfGhIjKlMnOpQ"]
        db_session.refresh(account)
        assert account.root_folder_ids == ["1AbCdEfGhIjKlMnOpQ"]
        assert account.status == status, "set_roots must not itself change the credential's status"
        db_session.delete(account)
        db_session.flush()


def test_set_roots_refuses_a_disconnected_account_the_same_way_as_no_account(
    db_session: Session, admin_user: User
) -> None:
    """Unlike `revoked`/`expired` above, a Drive the user unhooked on purpose has no
    folders to configure -- the same refusal `_present` gives `usable` for a
    disconnected row."""
    _connected_drive_account(db_session, admin_user, status="disconnected")
    with pytest.raises(Conflict, match="Impostazioni → Drive") as caught:
        _drive_service_account(db_session).set_roots(
            DriveRootsUpdate(root_folder_ids=["1AbCdEfGhIjKlMnOpQ"]), _drive_actor(admin_user)
        )
    assert not isinstance(caught.value, DriveCredentialRevoked)


def test_set_roots_without_a_drive_account_is_a_conflict(
    db_session: Session, admin_user: User
) -> None:
    with pytest.raises(Conflict, match="Impostazioni → Drive"):
        _drive_service_account(db_session).set_roots(
            DriveRootsUpdate(root_folder_ids=["1AbCdEfGhIjKlMnOpQ"]), _drive_actor(admin_user)
        )


def test_set_roots_is_refused_for_a_readonly_actor(db_session: Session, admin_user: User) -> None:
    from pigrocrm.core.errors import PermissionDenied  # noqa: PLC0415

    _connected_drive_account(db_session, admin_user)
    reader = Actor(id=admin_user.id, type="user", role="readonly")
    with pytest.raises(PermissionDenied):
        _drive_service_account(db_session).set_roots(
            DriveRootsUpdate(root_folder_ids=["1AbCdEfGhIjKlMnOpQ"]), reader
        )
