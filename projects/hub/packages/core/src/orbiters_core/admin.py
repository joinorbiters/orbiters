"""Admins and their sessions: who may read the hub, and the cookie that says so."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbiters_core.config import Settings
from orbiters_core.errors import NotFound, ValidationFailed
from orbiters_core.models import NAME_MAX_LENGTH, AdminSession, AdminUser

ENTITY = "admin"
PASSWORD_MIN_LENGTH = 10
_hasher = PasswordHasher()


class AdminRead(BaseModel):
    """An admin as the area shows them: never the hash. `attivo` and `created_at` are
    here for the list of admins (ORB-123); `/auth/me` carries them too, harmlessly."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    nome: str
    attivo: bool
    created_at: datetime


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AdminService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def list(self) -> list[AdminRead]:
        """Every admin, oldest first, so the page reads as a history (ORB-123)."""
        rows = self.session.scalars(
            select(AdminUser).order_by(AdminUser.created_at, AdminUser.id)
        ).all()
        return [AdminRead.model_validate(row) for row in rows]

    def create(self, email: str, nome: str, password: str) -> AdminRead:
        """`orbiters createadmin`, and since ORB-123 the form in the admin area. Refuses
        a second admin with the same address, a blank or over-long name and a password
        shorter than ten characters; hashes with argon2, never stores it."""
        email = self._checked_email(email)
        nome = self._checked_nome(nome)
        self._check_password(password)
        row = AdminUser(email=email, nome=nome, password_hash=_hasher.hash(password))
        self.session.add(row)
        self.session.commit()
        return AdminRead.model_validate(row)

    def update(
        self,
        admin_id: UUID,
        *,
        nome: str | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> AdminRead:
        """The pencil on a row (ORB-129): a new name, a new address, a new password, any
        of them, under the same rules as `create`. `None` means «keep it». The row's own
        address is no duplicate of itself; open sessions hang on the id and survive."""
        row = self.session.get(AdminUser, admin_id)
        if row is None:
            raise NotFound(ENTITY, admin_id)
        if email is not None:
            row.email = self._checked_email(email, except_id=row.id)
        if nome is not None:
            row.nome = self._checked_nome(nome)
        if password is not None:
            self._check_password(password)
            row.password_hash = _hasher.hash(password)
        self.session.commit()
        return AdminRead.model_validate(row)

    def _checked_email(self, email: str, except_id: UUID | None = None) -> str:
        email = email.strip().lower()
        other = self._by_email(email)
        if other is not None and other.id != except_id:
            raise ValidationFailed(ENTITY, "email", "esiste già un amministratore con questa email")
        return email

    @staticmethod
    def _checked_nome(nome: str) -> str:
        nome = nome.strip()
        if not nome:
            raise ValidationFailed(ENTITY, "nome", "serve un nome")
        if len(nome) > NAME_MAX_LENGTH:
            raise ValidationFailed(ENTITY, "nome", f"al massimo {NAME_MAX_LENGTH} caratteri")
        return nome

    @staticmethod
    def _check_password(password: str) -> None:
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ValidationFailed(ENTITY, "password", f"almeno {PASSWORD_MIN_LENGTH} caratteri")

    def authenticate(self, email: str, password: str) -> AdminRead | None:
        """The user, or `None` -- for an unknown address, a wrong password and a
        deactivated admin alike, so the login form cannot tell them apart."""
        row = self._by_email(email.strip().lower())
        if row is None or not row.attivo:
            return None
        try:
            _hasher.verify(row.password_hash, password)
        except VerifyMismatchError:
            return None
        return AdminRead.model_validate(row)

    def open_session(self, user_id: UUID) -> str:
        """A fresh opaque token. Only its hash is stored; the raw value goes into the
        cookie and nowhere else."""
        raw = secrets.token_urlsafe(32)
        self.session.add(
            AdminSession(user_id=user_id, token_hash=_hash_token(raw), expires_at=self._deadline())
        )
        self.session.commit()
        return raw

    def resolve(self, raw: str | None) -> AdminRead | None:
        """The admin behind a cookie, or `None`. Slides the expiry forward on every hit,
        and forgets a session past its deadline the moment it is presented."""
        if not raw:
            return None
        row = self.session.scalar(
            select(AdminSession).where(AdminSession.token_hash == _hash_token(raw))
        )
        if row is None:
            return None
        now = datetime.now(UTC)
        if row.expires_at <= now:
            self.session.delete(row)
            self.session.commit()
            return None
        user = self.session.get(AdminUser, row.user_id)
        if user is None or not user.attivo:
            return None
        row.expires_at = self._deadline(now)
        self.session.commit()
        return AdminRead.model_validate(user)

    def close_session(self, raw: str | None) -> None:
        if not raw:
            return
        row = self.session.scalar(
            select(AdminSession).where(AdminSession.token_hash == _hash_token(raw))
        )
        if row is not None:
            self.session.delete(row)
            self.session.commit()

    def _deadline(self, now: datetime | None = None) -> datetime:
        return (now or datetime.now(UTC)) + timedelta(days=self.settings.admin_session_days)

    def _by_email(self, email: str) -> AdminUser | None:
        return self.session.scalar(select(AdminUser).where(func.lower(AdminUser.email) == email))
