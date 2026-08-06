from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# RFC 7518 Section 3.2: an HS256 key shorter than 32 bytes is weaker than the
# algorithm's own output size. PyJWT already warns about this; validating here turns
# a silent warning (easy to miss in production logs) into a startup failure instead.
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIGROCRM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pigrocrm:pigrocrm@localhost:5432/pigrocrm"
    jwt_secret: str = "change-me-in-production-please-set-a-real-secret"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    # Must stay True in production: it is what stops the auth cookies from ever being
    # sent over plain HTTP. It exists as a *setting* rather than a hardcoded True only
    # because of one browser: Chrome and Firefox treat "localhost" as a secure context
    # and accept a `Secure` cookie over plain HTTP there, but Safari does not and has
    # no plan to. Local development (slice 1B's Vite proxy) serves the API over
    # http://localhost with no TLS, so without an escape hatch, login on Safari in dev
    # would return 200 while the browser silently discarded the cookie -- every
    # request after that looks unauthenticated with no error anywhere to explain why.
    # Set PIGROCRM_COOKIE_SECURE=false for that one case. Anyone tempted to flip this
    # in production because "it's just a flag" should re-read this paragraph first.
    cookie_secure: bool = True

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_must_be_long_enough(cls, value: str) -> str:
        if len(value) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"jwt_secret must be at least {MIN_JWT_SECRET_LENGTH} characters long "
                "(a short HS256 key is weaker than the algorithm itself, RFC 7518 "
                "Section 3.2)"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
