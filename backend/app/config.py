"""Settings loaded from environment variables (plus a local .env file in development).

pydantic-settings fills each field from the environment variable of the same name
(DATABASE_URL -> database_url) and validates its type at startup, so a missing or
malformed setting fails immediately instead of deep inside a request.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repo root, where a developer's .env lives. In Docker the
# file does not exist and the environment variables come from docker-compose.yml.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT / ".env", extra="ignore")

    database_url: str
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
