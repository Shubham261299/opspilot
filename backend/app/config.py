"""Settings loaded from environment variables (plus a local .env file in development).

pydantic-settings fills each field from the environment variable of the same name
(DATABASE_URL -> database_url) and validates its type at startup, so a missing or
malformed setting fails immediately instead of deep inside a request.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repo root, where a developer's .env lives. In Docker the
# file does not exist and the environment variables come from docker-compose.yml.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT / ".env", extra="ignore")

    database_url: str
    log_level: str = "INFO"
    # Folder holding suppliers.csv and product_master.csv (Docker sets /app/seed_data).
    seed_data_dir: Path = _REPO_ROOT / "sample_data"
    max_upload_mb: int = 5
    # Pin "today" (e.g. 2026-09-24, the sample data's date) for demos; unset = the real date.
    app_today: date | None = None
    # The shop's own name in WhatsApp chats; its messages are replies, not orders.
    shop_name: str = "Sharma Traders"

    # Language model, through LiteLLM (decision 024). "ollama_chat/<model>" = a local Ollama.
    llm_model: str = "ollama_chat/qwen2.5:7b"
    llm_base_url: str | None = "http://localhost:11434"
    llm_api_key: SecretStr | None = None  # only for hosted models; SecretStr hides it in logs
    llm_timeout_s: float = 180  # a CPU-only laptop can take a while on a long chat


@lru_cache
def get_settings() -> Settings:
    return Settings()
