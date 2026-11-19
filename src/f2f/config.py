from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    public_base_url: str = "http://127.0.0.1:8000"
    session_ttl_hours: float = 12.0
    templates_path: Path = PROJECT_ROOT / "templates.json"
    fonts_dir: Path = Path("/Library/Fonts")

    # manual until a live droid send is verified on this machine (see README, "droid" backend).
    sender_backend: Literal["droid", "manual", "google"] = "manual"
    droid_bin: str = "droid"
    droid_auto: Literal["low", "medium", "high"] = "medium"
    droid_timeout_seconds: int = 240
    droid_model: str | None = None

    genai_platform_api_key: str | None = None
    genai_base_url: str = "https://genai-platform.is.adyen.com/v1"
    genai_model: str = "gemma4-31b"
    genai_timeout_seconds: float = 60.0

    google_client_id: str | None = None
    google_client_secret: str | None = None
    tl_allowed_emails: str = ""

    admin_passcode: str | None = None
    secure_cookies: bool = False

    @property
    def allowed_tl_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.tl_allowed_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
