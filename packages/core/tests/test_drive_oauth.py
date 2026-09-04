"""The Drive credential: a second grant, a second row, the same key (spec 9 §5)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from pigrocrm.core.auth.models import User
from pigrocrm.core.drive.models import GoogleDriveAccount
from pigrocrm.core.drive.schemas import (
    DRIVE_REQUESTED_SCOPES,
    DriveRootsUpdate,
    GoogleDriveAccountRead,
)
from pigrocrm.core.gmail.models import GoogleOAuthState


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
