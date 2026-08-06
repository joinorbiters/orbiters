from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from pydantic import BaseModel

from pigrocrm.core.config import Settings
from pigrocrm.core.errors import ValidationFailed

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]


class TokenPayload(BaseModel):
    sub: UUID
    role: str | None
    type: TokenType
    exp: datetime


def _issue(
    user_id: UUID, role: str | None, token_type: TokenType, delta: timedelta, settings: Settings
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def issue_access_token(user_id: UUID, role: str, settings: Settings) -> str:
    return _issue(
        user_id, role, "access", timedelta(minutes=settings.access_token_minutes), settings
    )


def issue_refresh_token(user_id: UUID, settings: Settings) -> str:
    return _issue(user_id, None, "refresh", timedelta(days=settings.refresh_token_days), settings)


def decode_token(token: str, settings: Settings, *, expected_type: TokenType) -> TokenPayload:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise ValidationFailed("session", "token", "token non valido o scaduto") from exc

    if claims.get("type") != expected_type:
        raise ValidationFailed("session", "token", "tipo di token errato", expected=expected_type)
    return TokenPayload(
        sub=UUID(claims["sub"]),
        role=claims.get("role"),
        type=claims["type"],
        exp=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )
