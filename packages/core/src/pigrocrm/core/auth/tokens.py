from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

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
    # Only refresh tokens carry one -- see issue_refresh_token. None for access tokens.
    jti: UUID | None = None


def _issue(
    user_id: UUID,
    role: str | None,
    token_type: TokenType,
    delta: timedelta,
    settings: Settings,
    *,
    jti: UUID | None = None,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
    }
    if jti is not None:
        claims["jti"] = str(jti)
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def issue_access_token(user_id: UUID, role: str, settings: Settings) -> str:
    return _issue(
        user_id, role, "access", timedelta(minutes=settings.access_token_minutes), settings
    )


def issue_refresh_token(user_id: UUID, settings: Settings, *, jti: UUID | None = None) -> str:
    """`jti` identifies this exact token: two refresh tokens issued in the same second
    would otherwise carry identical `iat`/`exp` claims, and HS256 over identical claims
    with the same key is deterministic -- byte-for-byte the same token, which defeats
    rotation entirely. A fresh random `jti` is generated whenever the caller does not
    supply one, so two tokens can never collide; `RefreshTokenService.issue` supplies
    its own so the same value can be persisted for later revocation/consumption."""
    return _issue(
        user_id,
        None,
        "refresh",
        timedelta(days=settings.refresh_token_days),
        settings,
        jti=jti if jti is not None else uuid4(),
    )


def decode_token(token: str, settings: Settings, *, expected_type: TokenType) -> TokenPayload:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise ValidationFailed("session", "token", "token non valido o scaduto") from exc

    if claims.get("type") != expected_type:
        raise ValidationFailed("session", "token", "tipo di token errato", expected=expected_type)

    # A signature can be valid while the payload is still missing or malformed --
    # e.g. no "sub", no "exp", or a "sub" that is not a UUID. Building TokenPayload
    # from claims must never let a raw KeyError/ValueError escape: this function's
    # contract is "return a TokenPayload or raise a domain error," never a bare
    # stdlib exception.
    try:
        raw_jti = claims.get("jti")
        return TokenPayload(
            sub=UUID(claims["sub"]),
            role=claims.get("role"),
            type=claims["type"],
            exp=datetime.fromtimestamp(claims["exp"], tz=UTC),
            jti=UUID(raw_jti) if raw_jti is not None else None,
        )
    except (KeyError, ValueError) as exc:
        raise ValidationFailed("session", "token", "token malformato") from exc
