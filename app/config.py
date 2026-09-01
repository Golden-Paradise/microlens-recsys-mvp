from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
    )

    name: str = "MicroLens Recsys MVP"
    secret_key: str = Field(default="development-only-change-me", min_length=16)
    session_max_age_seconds: int = Field(default=28_800, ge=60)
    database_url: str = "sqlite:///var/app.db"
    processed_dir: Path = Path("data/processed")
    artifact_dir: Path = Path("artifacts")
    cookie_secure: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65_535)
    seed_demo_data: bool = True
    seed_official_catalog: bool = True
    demo_password: str = Field(default="DemoPass123!", min_length=8, max_length=128)
