"""Application configuration loaded from environment variables / ``.env``.

Every tunable lives here so no module hardcodes credentials, paths or limits.
"""

from __future__ import annotations

import secrets
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "StegoLab"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # --- Database -------------------------------------------------------
    database_url: str = Field(
        default=f"sqlite:///{(BACKEND_DIR / 'storage' / 'stegolab.db').as_posix()}",
        description="SQLAlchemy URL. PostgreSQL in production: postgresql+psycopg://user:pass@host/db",
    )

    # --- Secrets --------------------------------------------------------
    secret_key: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False

    # --- Paths ----------------------------------------------------------
    model_path: Path = BACKEND_DIR / "models"
    upload_dir: Path = BACKEND_DIR / "storage"
    dataset_dir: Path = BACKEND_DIR.parent / "data" / "dataset"
    # Public-domain / CC0 held-out images shipped with the repository (used when the full
    # dataset has not been generated, e.g. on a fresh clone).
    demo_carriers_dir: Path = BACKEND_DIR / "demo_carriers"

    # --- Upload validation ----------------------------------------------
    max_upload_size: int = 20 * 1024 * 1024  # bytes
    max_payload_file_size: int = 2 * 1024 * 1024  # bytes, for file payloads
    max_image_pixels: int = 36_000_000  # decompression-bomb guard
    min_image_dimension: int = 64
    max_image_dimension: int = 8192

    # --- Retention (hours) ----------------------------------------------
    temp_retention_hours: int = 24
    retention_sweep_minutes: int = 30

    # --- Payload key derivation (Argon2id) -------------------------------
    kdf_time_cost: int = 3
    kdf_memory_kib: int = 65536  # 64 MiB
    kdf_parallelism: int = 4

    # --- Auth policy ----------------------------------------------------
    allow_registration: bool = True
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # --- Rate limiting (requests per window) ---------------------------
    rate_limit_window_seconds: int = 60
    rate_limit_auth: int = 10
    rate_limit_heavy: int = 30
    rate_limit_default: int = 240

    # --- ML -------------------------------------------------------------
    device: Literal["auto", "cuda", "cpu"] = "auto"
    inference_tile: int = 256
    max_inference_tiles: int = 64

    # --- CORS -------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Bootstrap admin (only used by `python -m app.cli bootstrap-admin`) ---
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_name: str = "Administrator"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        for name in ("secret_key", "jwt_secret"):
            value = getattr(self, name)
            if value and len(value) >= 32:
                continue
            if self.app_env == "production":
                raise ValueError(f"{name.upper()} must be set to at least 32 characters in production")
            # Development/test fallback: ephemeral secret. Tokens die on restart.
            warnings.warn(
                f"{name.upper()} not configured - using an ephemeral random value "
                "(run scripts/init_env.py to create backend/.env)",
                stacklevel=2,
            )
            setattr(self, name, secrets.token_urlsafe(48))
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def artifacts_dir(self) -> Path:
        return self.upload_dir / "artifacts"

    @property
    def reports_dir(self) -> Path:
        return self.upload_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    return settings
