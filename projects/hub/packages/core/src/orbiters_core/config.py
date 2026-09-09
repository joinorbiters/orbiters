"""The hub's settings, read once from the environment (`ORBITERS_*`) and `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORBITERS_", env_file=".env", extra="ignore")

    # The hub's own database. Nothing here derives a name from another product's URL:
    # the old `PIGROCRM_ORBITERS_DATABASE_URL` fallback ("the CRM's server with the
    # database renamed") is exactly the coupling this project was split to remove.
    database_url: str = "postgresql+psycopg://orbiters:orbiters@localhost:5433/orbiters"

    # --- ChatGPT Ads: the signup conversion --------------------------------------------
    # The pixel measures the signup from the browser; these values are the server half
    # (`conversions.py`), which exists because the browser event is the one that gets
    # lost: an ad blocker, a network that drops the SDK, a tab closed before the ping
    # leaves. `openai_pixel_id` is public (it sits in the website's markup) and is
    # repeated here because the conversions endpoint wants it in the query string;
    # `openai_conversions_api_key` is a secret with write access to the conversion data
    # source and lives in the server's `.env` only. With either empty no server event is
    # sent, and that is not an error: it is a site that runs no campaigns.
    openai_pixel_id: str = ""
    openai_conversions_api_key: str = ""
    # The page where the conversion happens, required by the API for a `web` event and
    # taken from here rather than from the request: a `source_url` that arrives from the
    # client is a string the caller chose, forwarded to a third party as it came.
    signup_url: str = "https://joinorbiters.com/"
    # Whether to also send OpenAI the SHA-256 of the address. It improves attribution,
    # and a hash of an email is still that person's identifier: whoever runs the site
    # decides, and the default is no.
    openai_conversions_send_hashed_email: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
