import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application configuration loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General App Config
    APP_NAME: str = "JobPilot"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./jobpilot.db"

    # LLM Config
    DEFAULT_LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"

    # Browser Config - Headed visible browser with slow-mo for real-time visualization
    BROWSER_HEADLESS: bool = False
    BROWSER_SLOW_MO: int = 300
    BROWSER_TIMEOUT_MS: int = 30000
    BROWSER_VISUAL_HIGHLIGHT: bool = True

    # Thresholds
    CONFIDENCE_THRESHOLD_AUTO: float = 0.90
    CONFIDENCE_THRESHOLD_SUGGEST: float = 0.70

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV.lower() in ("dev", "development")


settings = Settings()
