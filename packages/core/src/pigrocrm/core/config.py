from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIGROCRM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pigrocrm:pigrocrm@localhost:5432/pigrocrm"
    jwt_secret: str = "change-me-in-production"
    access_token_minutes: int = 15
    refresh_token_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
