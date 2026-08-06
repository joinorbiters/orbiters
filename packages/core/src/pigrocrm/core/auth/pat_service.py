import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor, Role
from pigrocrm.core.auth.models import User
from pigrocrm.core.auth.pat_models import PersonalAccessToken
from pigrocrm.core.errors import Conflict, NotFound, ValidationFailed

PAT_PREFIX = "pgc_"
PREFIX_VISIBLE_CHARS = 8
# Used for every way `resolve()` can fail -- unknown token, revoked token, or a token
# whose owning user was deactivated -- so the three are indistinguishable from the
# outside. A leaked PAT must not double as an oracle for "is this still worth using":
# the same discipline `UserService.authenticate` already applies with its dummy hash,
# here applied to error content instead of timing.
INVALID_TOKEN = "token non valido o revocato"


class PatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


def _digest(raw: str) -> str:
    """SHA-256, not argon2: lookup is by hash, so it must be deterministic. Safe here
    because the token is 32 random bytes, not a human-chosen password."""
    return hashlib.sha256(raw.encode()).hexdigest()


class PatService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, nome: str, actor: Actor) -> tuple[PatRead, str]:
        if actor.id is None:
            raise ValidationFailed("token", "actor", "serve un utente autenticato")

        raw = PAT_PREFIX + secrets.token_urlsafe(32)
        record = PersonalAccessToken(
            user_id=actor.id,
            nome=nome,
            token_hash=_digest(raw),
            prefix=raw[: len(PAT_PREFIX) + PREFIX_VISIBLE_CHARS],
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError as exc:
            # token_hash is unique=True. A collision on 32 random bytes is
            # astronomically unlikely -- there is no pre-check here, unlike
            # UserService's email conflict, because one would only add ceremony
            # without meaningfully reducing the risk. But the constraint (not this
            # comment) is what actually guarantees uniqueness, so the same rollback
            # discipline as UserService.create still applies: without it, the
            # session is left poisoned for whatever the caller does next.
            self.session.rollback()
            raise Conflict(
                "personal_access_token", "collisione imprevista sul token, riprova"
            ) from exc
        # The raw value is returned exactly once and never stored.
        return PatRead.model_validate(record), raw

    def list(self, actor: Actor) -> list[PatRead]:
        stmt = (
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == actor.id)
            .order_by(PersonalAccessToken.created_at.desc())
        )
        return [PatRead.model_validate(r) for r in self.session.execute(stmt).scalars()]

    def revoke(self, pat_id: UUID, actor: Actor) -> None:
        stmt = select(PersonalAccessToken).where(
            PersonalAccessToken.id == pat_id, PersonalAccessToken.user_id == actor.id
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            raise NotFound("personal_access_token", pat_id)
        record.revoked_at = datetime.now(UTC)
        self.session.commit()

    def resolve(self, raw_token: str) -> Actor:
        stmt = select(PersonalAccessToken).where(
            PersonalAccessToken.token_hash == _digest(raw_token)
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None or record.revoked_at is not None:
            raise ValidationFailed("token", "token", INVALID_TOKEN)

        user = self.session.get(User, record.user_id)
        if user is None or not user.attivo:
            # Same message and details as above, on purpose -- see INVALID_TOKEN.
            raise ValidationFailed("token", "token", INVALID_TOKEN)

        record.last_used_at = datetime.now(UTC)
        self.session.commit()
        role: Role = user.ruolo  # type: ignore[assignment]
        # type="mcp": a PAT identifies an agent, which is what makes the timeline honest.
        return Actor(id=user.id, type="mcp", role=role)
