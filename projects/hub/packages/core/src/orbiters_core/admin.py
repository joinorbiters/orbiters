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
from orbiters_core.errors import ValidationFailed
from orbiters_core.models import AdminSession, AdminUser

ENTITY = "admin"
PASSWORD_MIN_LENGTH = 10
_hasher = PasswordHasher()


class AdminRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    nome: str


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AdminService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def create(self, email: str, nome: str, password: str) -> AdminRead:
        """`orbiters createadmin`. Refuses a second admin with the same address and a
        password shorter than ten characters; hashes with argon2, never stores it."""
        email = email.strip().lower()
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ValidationFailed(ENTITY, "password", f"almeno {PASSWORD_MIN_LENGTH} caratteri")
        if self._by_email(email) is not None:
            raise ValidationFailed(ENTITY, "email", "esiste già un amministratore con questa email")
        row = AdminUser(email=email, nome=nome.strip(), password_hash=_hasher.hash(password))
        self.session.add(row)
        self.session.commit()
        return AdminRead.model_validate(row)

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
