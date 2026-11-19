"""Environment variables (spec §3.1). Values come from the process environment or `server/.env`."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import SERVER_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SERVER_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    kb_database_url: str = Field("", alias="KB_DATABASE_URL")
    kb_version: str = Field("", alias="KB_VERSION")

    llm_provider: Literal["anthropic", "openai", "gemini", "mock"] = Field(alias="LLM_PROVIDER")
    llm_model: str = Field(alias="LLM_MODEL")
    llm_api_key: str = Field("", alias="LLM_API_KEY")
    llm_timeout_s: int = Field(60, alias="LLM_TIMEOUT_S")

    embed_mode: Literal["bge", "mock"] = Field("bge", alias="EMBED_MODE")

    app_demo_token: str = Field(alias="APP_DEMO_TOKEN")

    kb_mode: Literal["on", "off"] = Field("on", alias="KB_MODE")
    home_context: Literal["on", "off"] = Field("on", alias="HOME_CONTEXT")
    kb_sample: float = Field(1.0, gt=0, le=1, alias="KB_SAMPLE")
    other_home: Literal["off"] = Field("off", alias="OTHER_HOME")

    demo_mode: bool = Field(False, alias="DEMO_MODE")
    image_dir: str = Field("/tmp/spira-images", alias="IMAGE_DIR")
    calendar_hmac_key: str = Field(alias="CALENDAR_HMAC_KEY")
    tz: str = Field("Asia/Seoul", alias="TZ")

    @model_validator(mode="after")
    def _check(self) -> Settings:
        missing = []
        if not self.app_demo_token:
            missing.append("APP_DEMO_TOKEN")
        if len(self.calendar_hmac_key) < 32:
            missing.append("CALENDAR_HMAC_KEY (32+ characters)")
        if not self.llm_model:
            missing.append("LLM_MODEL")
        if self.llm_provider != "mock" and not self.llm_api_key:
            missing.append("LLM_API_KEY")
        if self.kb_mode == "on":
            if not self.kb_database_url:
                missing.append("KB_DATABASE_URL (KB_MODE=on)")
            if not self.kb_version:
                missing.append("KB_VERSION (KB_MODE=on)")
        if missing:
            raise ValueError("Set in server/.env: " + ", ".join(missing))
        return self

    @property
    def kb_version_number(self) -> int:
        """kb-v3 -> 3 (versions are cumulative, spec §8.4)."""
        tail = self.kb_version.rsplit("-v", 1)[-1]
        return int(tail) if tail.isdigit() else 0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
