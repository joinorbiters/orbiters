import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.passwords import hash_password, verify_password
from pigrocrm.core.auth.schemas import UserCreate, UserUpdate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.errors import Conflict, PermissionDenied, ValidationFailed

ADMIN = Actor(id=None, type="system", role="admin")
COLLAB = Actor(id=None, type="user", role="collaboratore")


def test_password_hash_is_argon2_and_never_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2")
    assert "correct horse" not in hashed
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_the_same_password_hashes_differently_each_time() -> None:
    assert hash_password("same") != hash_password("same"), "argon2 must salt per hash"


def test_create_user_stores_a_hash_and_normalises_the_email(db_session: Session) -> None:
    service = UserService(db_session)
    user = service.create(
        UserCreate(email="  Mario@Example.IT ", password="supersegreta1", nome="Ivan", ruolo="admin"),
        ADMIN,
    )
    assert user.email == "mario@example.it"
    assert user.ruolo == "admin"
    assert user.attivo is True
    assert not hasattr(user, "password_hash"), "UserRead must never expose the hash"


def test_duplicate_email_is_a_conflict(db_session: Session) -> None:
    service = UserService(db_session)
    service.create(
        UserCreate(email="a@b.it", password="supersegreta1", nome="A", ruolo="admin"), ADMIN
    )
    with pytest.raises(Conflict) as exc:
        service.create(
            UserCreate(email="A@B.it", password="supersegreta1", nome="A2", ruolo="admin"), ADMIN
        )
    assert exc.value.details["entity"] == "user"


def test_short_password_is_rejected(db_session: Session) -> None:
    service = UserService(db_session)
    with pytest.raises(ValidationFailed) as exc:
        service.create(UserCreate(email="c@d.it", password="corta", nome="C", ruolo="admin"), ADMIN)
    assert exc.value.details["field"] == "password"


def test_only_admins_manage_users(db_session: Session) -> None:
    service = UserService(db_session)
    with pytest.raises(PermissionDenied) as exc:
        service.create(
            UserCreate(email="e@f.it", password="supersegreta1", nome="E", ruolo="readonly"), COLLAB
        )
    assert exc.value.details["required_roles"] == ["admin"]


def test_authenticate_accepts_correct_credentials(db_session: Session) -> None:
    service = UserService(db_session)
    service.create(
        UserCreate(email="g@h.it", password="supersegreta1", nome="G", ruolo="admin"), ADMIN
    )
    assert service.authenticate("G@H.it", "supersegreta1").email == "g@h.it"


@pytest.mark.parametrize(
    "email,password", [("g@h.it", "sbagliata"), ("nope@h.it", "supersegreta1")]
)
def test_authenticate_rejects_bad_credentials_without_saying_which(
    db_session: Session, email: str, password: str
) -> None:
    """Distinguishing 'unknown user' from 'wrong password' leaks which emails exist."""
    service = UserService(db_session)
    service.create(
        UserCreate(email="g@h.it", password="supersegreta1", nome="G", ruolo="admin"), ADMIN
    )
    with pytest.raises(ValidationFailed) as exc:
        service.authenticate(email, password)
    assert exc.value.details["reason"] == "credenziali non valide"


def test_deactivated_user_cannot_authenticate(db_session: Session) -> None:
    service = UserService(db_session)
    user = service.create(
        UserCreate(email="i@j.it", password="supersegreta1", nome="I", ruolo="admin"), ADMIN
    )
    service.update(user.id, UserUpdate(attivo=False), ADMIN)
    with pytest.raises(ValidationFailed):
        service.authenticate("i@j.it", "supersegreta1")
