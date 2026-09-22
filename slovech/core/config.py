"""Validated configuration; importing modules never creates files or starts clients."""

import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
SAFE_ID_REGEX = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")
SAFE_AUDIO_REGEX = re.compile(r"[a-zA-Z0-9_-]+\.(mp3|m4a|wav|ogg|aac)\Z", re.I)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )
    environment: str = "development"
    bot_token: SecretStr = SecretStr("")
    admin_secret: SecretStr = SecretStr("")
    admin_user_id: int = 0
    domain: str = "http://localhost:8000"
    data_dir: Path = ROOT / "var/data"
    audio_dir: Path = ROOT / "var/audio"
    static_dir: Path = ROOT / "web"
    telegram_api_url: str = ""
    telegram_local_file_root: Path | None = None
    storage_group_writable: bool = False
    gemini_api_keys: SecretStr = SecretStr("")
    gemini_models: str = "gemini-2.5-flash"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_models: str = ""
    youtube_proxy: str = ""
    auth_max_age: int = 3600
    max_upload_bytes: int = 300 * 1024 * 1024
    max_audio_seconds: int = 10800
    max_pending_jobs: int = 100
    max_user_jobs: int = 3
    job_timeout_seconds: int = 1800

    @model_validator(mode="after")
    def validate_settings(self):
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("Unsupported ENVIRONMENT")
        url = urlsplit(self.domain)
        if (
            url.scheme not in {"http", "https"}
            or url.username
            or url.password
            or not url.netloc
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("DOMAIN must be an HTTP(S) origin")
        self.domain = self.domain.rstrip("/")
        for name in (
            "auth_max_age",
            "max_upload_bytes",
            "max_audio_seconds",
            "max_pending_jobs",
            "max_user_jobs",
            "job_timeout_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.environment == "production":
            if url.scheme != "https" or not self.bot_token.get_secret_value():
                raise ValueError("Production requires HTTPS DOMAIN and BOT_TOKEN")
        if self.telegram_local_file_root is not None:
            if not self.telegram_api_url or not self.telegram_local_file_root.is_absolute():
                raise ValueError(
                    "Local Telegram files require an API URL and an absolute shared root"
                )
        secret = self.admin_secret.get_secret_value()
        if secret and (len(secret) < 32 or self.admin_user_id <= 0):
            raise ValueError("Admin access requires a 32+ character secret and ADMIN_USER_ID")
        return self

    def prepare(self):
        os.umask(0o007 if self.storage_group_writable else 0o077)
        mode = 0o2770 if self.storage_group_writable else 0o700
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=mode)
        self.audio_dir.mkdir(parents=True, exist_ok=True, mode=mode)

    def validate_worker(self):
        if not self.bot_token.get_secret_value() or not self.gemini_api_keys.get_secret_value():
            raise ValueError("Bot/worker requires BOT_TOKEN and GEMINI_API_KEYS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
