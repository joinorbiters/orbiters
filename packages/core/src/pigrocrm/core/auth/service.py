from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.passwords import dummy_hash, hash_password, verify_password
from pigrocrm.core.auth.repository import UserRepository
from pigrocrm.core.auth.schemas import MIN_PASSWORD_LENGTH, UserCreate, UserRead, UserUpdate
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed

INVALID_CREDENTIALS = "credenziali non valide"


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = UserRepository(session)

    def create(self, data: UserCreate, actor: Actor) -> UserRead:
        actor.require_admin("create_user")
        if len(data.password) < MIN_PASSWORD_LENGTH:
            raise ValidationFailed(
                "user",
                "password",
                f"deve avere almeno {MIN_PASSWORD_LENGTH} caratteri",
                expected=f">= {MIN_PASSWORD_LENGTH} caratteri",
            )
        if self.repo.get_by_email(data.email):
            raise Conflict("user", "esiste già un utente con questa email", email=data.email)

        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            nome=data.nome,
            ruolo=data.ruolo,
            attivo=True,
            tariffa_oraria_default=data.tariffa_oraria_default,
            costo_orario_default=data.costo_orario_default,
        )
        try:
            self.repo.add(user)
            self.session.commit()
        except IntegrityError as exc:
            # The pre-check above cannot cover a race between two concurrent requests:
            # both can pass the SELECT before either has committed. Here the database
            # constraint is the only authority left, and the rollback is mandatory --
            # without it the session stays unusable for whatever the caller does next.
            self.session.rollback()
            raise Conflict(
                "user", "esiste già un utente con questa email", email=data.email
            ) from exc
        return UserRead.model_validate(user)

    def update(self, user_id: UUID, data: UserUpdate, actor: Actor) -> UserRead:
        actor.require_admin("update_user")
        user = self.repo.get(user_id)
        if user is None:
            raise NotFound("user", user_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(user, field, value)
        self.session.commit()
        return UserRead.model_validate(user)

    def list(self, actor: Actor) -> list[UserRead]:
        actor.require_admin("list_users")
        return [UserRead.model_validate(u) for u in self.repo.list_all()]

    def count(self) -> int:
        return self.repo.count()

    def authenticate(self, email: str, password: str) -> UserRead:
        user = self.repo.get_by_email(email)
        # Compare against a precomputed constant hash when the user is missing, so both
        # paths cost exactly one verify and timing does not reveal which emails exist.
        reference = user.password_hash if user else dummy_hash()
        ok = verify_password(password, reference)
        if user is None or not ok or not user.attivo:
            raise ValidationFailed("user", "credentials", INVALID_CREDENTIALS)
        return UserRead.model_validate(user)
