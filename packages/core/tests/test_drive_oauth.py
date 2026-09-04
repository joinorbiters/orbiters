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
from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.oauth import GoogleDriveOAuthService
from pigrocrm.core.drive.schemas import (
    DRIVE_REQUESTED_SCOPES,
    DriveRootsUpdate,
    GoogleDriveAccountRead,
)
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.crypto import seal, unseal
from pigrocrm.core.gmail.models import GoogleAccount, GoogleOAuthState
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport


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
