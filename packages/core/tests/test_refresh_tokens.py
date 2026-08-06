from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.refresh_models import RefreshToken
from pigrocrm.core.auth.refresh_service import RefreshTokenService
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import UserCreate, UserUpdate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.auth.tokens import decode_token
from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed

SETTINGS = Settings(jwt_secret="test-secret-not-for-production-and-32-chars-long")
ADMIN = Actor(id=None, type="system", role="admin")


def _make_user(db_session: Session, email: str = "refresh@test.it"):
    return UserService(db_session).create(
        UserCreate(email=email, password="supersegreta1", nome="Refresh", ruolo="admin"), ADMIN
    )


def test_issuing_twice_produces_two_different_tokens(db_session: Session) -> None:
    user = _make_user(db_session)
    service = RefreshTokenService(db_session)

    token_a = service.issue(user.id, SETTINGS)
    token_b = service.issue(user.id, SETTINGS)

    assert token_a != token_b


def test_consuming_marks_the_row_consumed(db_session: Session) -> None:
    user = _make_user(db_session)
    service = RefreshTokenService(db_session)
    token = service.issue(user.id, SETTINGS)
    jti = decode_token(token, SETTINGS, expected_type="refresh").jti
    assert jti is not None

    service.consume(jti, user.id)

    record = db_session.execute(select(RefreshToken).where(RefreshToken.jti == jti)).scalar_one()
    assert record.consumed_at is not None


def test_consuming_an_unknown_jti_is_rejected(db_session: Session) -> None:
    user = _make_user(db_session)
    service = RefreshTokenService(db_session)

    with pytest.raises(ValidationFailed):
        service.consume(uuid4(), user.id)


def test_consuming_the_same_jti_twice_is_rejected(db_session: Session) -> None:
    """This is the exact bug the review caught: rotation must actually rotate. Before
    the fix, nothing stopped the same refresh token from being consumed over and over,
    which is what let a stolen token keep working after the legitimate user rotated
    past it."""
    user = _make_user(db_session)
    service = RefreshTokenService(db_session)
    token = service.issue(user.id, SETTINGS)
    jti = decode_token(token, SETTINGS, expected_type="refresh").jti
    assert jti is not None

    service.consume(jti, user.id)

    with pytest.raises(ValidationFailed):
        service.consume(jti, user.id)


def test_reusing_a_consumed_token_revokes_every_other_valid_token_for_that_user(
    db_session: Session,
) -> None:
    """The standard response to replay: a consumed token being presented again is the
    signal that it was stolen, not that the legitimate user is confused. Rewarding that
    replay with a fresh pair of tokens would leave the thief inside, so the whole
    session family for this user is killed, not just the one token replayed."""
    user = _make_user(db_session)
    service = RefreshTokenService(db_session)

    token_a = service.issue(user.id, SETTINGS)  # e.g. session on device A
    token_b = service.issue(user.id, SETTINGS)  # e.g. session on device B, still unused
    jti_a = decode_token(token_a, SETTINGS, expected_type="refresh").jti
    jti_b = decode_token(token_b, SETTINGS, expected_type="refresh").jti
    assert jti_a is not None and jti_b is not None

    service.consume(jti_a, user.id)  # normal rotation of session A

    with pytest.raises(ValidationFailed):
        service.consume(jti_a, user.id)  # jti_a replayed -- triggers mass revocation

    # jti_b was never itself replayed, and was never even used -- but it must now be
    # dead too, because the replay above is exactly the case this design cannot ignore.
    with pytest.raises(ValidationFailed):
        service.consume(jti_b, user.id)


def test_a_refresh_token_from_a_different_user_is_rejected(db_session: Session) -> None:
    owner = _make_user(db_session, "owner@refresh.it")
    other = _make_user(db_session, "other@refresh.it")
    service = RefreshTokenService(db_session)
    token = service.issue(owner.id, SETTINGS)
    jti = decode_token(token, SETTINGS, expected_type="refresh").jti
    assert jti is not None

    with pytest.raises(ValidationFailed):
        service.consume(jti, other.id)


def test_an_expired_refresh_token_row_is_rejected(db_session: Session) -> None:
    """Independent of the JWT's own `exp` claim: `consume()` checks the row's
    `expires_at` itself, so an expired row is dead even if something upstream never
    decoded (or could not decode) the token to notice."""
    user = _make_user(db_session)
    already_expired = RefreshToken(
        jti=uuid4(),
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db_session.add(already_expired)
    db_session.commit()

    with pytest.raises(ValidationFailed):
        RefreshTokenService(db_session).consume(already_expired.jti, user.id)


def test_get_active_returns_the_user(db_session: Session) -> None:
    user = _make_user(db_session)
    fetched = UserRepository(db_session).get_active(user.id)
    assert fetched.id == user.id


def test_get_active_rejects_an_unknown_user(db_session: Session) -> None:
    with pytest.raises(ValidationFailed):
        UserRepository(db_session).get_active(uuid4())


def test_get_active_rejects_a_deactivated_user(db_session: Session) -> None:
    user = _make_user(db_session)
    UserService(db_session).update(user.id, UserUpdate(attivo=False), ADMIN)

    with pytest.raises(ValidationFailed):
        UserRepository(db_session).get_active(user.id)
