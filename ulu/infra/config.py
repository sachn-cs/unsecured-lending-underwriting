"""Application configuration via Pydantic Settings."""

from __future__ import annotations

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    """Shared configuration loaded from environment and .env files."""

    database_url: str = ""
    read_database_url: str = ""
    algod_token: str = ""
    algod_url: str = "http://localhost:4001"
    app_env: str = "development"
    log_level: str = "INFO"
    dlg_cap_ratio: float = 0.05
    npa_trigger_days: int = 120
    collateral_min_ratio: float = 0.05
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


class DevelopmentConfig(BaseConfig):
    """Development-specific overrides with safe defaults."""

    jwt_secret: str = "dev-secret-do-not-use-in-production-32bytes-long"


class ProductionConfig(BaseConfig):
    """Production config with mandatory secrets and URLs."""

    jwt_secret: str = Field(..., min_length=32)
    database_url: str = Field(...)


class TestingConfig(BaseConfig):
    """Testing config pointing to an in-memory SQLite database."""

    model_config = SettingsConfigDict(env_file=".env.test", env_file_encoding="utf-8")
    database_url: str = "sqlite+aiosqlite:///:memory:"


_env = os.environ.get("APP_ENV", "development")
settings: BaseConfig
if _env == "production":
    settings = ProductionConfig()  # type: ignore[call-arg]
elif _env == "testing":
    settings = TestingConfig()
else:
    settings = DevelopmentConfig()
