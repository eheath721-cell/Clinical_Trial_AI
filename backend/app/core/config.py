"""Environment-based configuration. All secrets come from the environment (or a local
.env file during development) and are never logged."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "TrialCompass"

    # Database
    database_url: str = "postgresql+psycopg://trialcompass:trialcompass@localhost:5432/trialcompass"

    # Security
    session_ttl_hours: int = 12
    cookie_secure: bool = False  # must be True behind HTTPS in staging/production
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Fernet key (urlsafe base64, 32 bytes) used to encrypt uploaded documents at rest.
    document_encryption_key: SecretStr | None = None
    # Salt for hashing IP addresses in the audit log (so raw IPs are never stored).
    audit_ip_salt: SecretStr = SecretStr("dev-only-change-me")

    # Data-handling guardrails
    # When False (default) the UI shows a persistent "synthetic data only" banner and the API
    # refuses to send any profile to an external LLM unless it is marked synthetic.
    allow_real_phi: bool = False
    llm_baa_in_place: bool = False  # set True only once a signed BAA with the LLM vendor exists

    # Storage
    document_storage_dir: Path = BACKEND_DIR / "var" / "documents"
    max_upload_mb: int = 15

    # Clinical trial data
    trial_source: Literal["live", "snapshot", "auto"] = "auto"
    ctgov_base_url: str = "https://clinicaltrials.gov/api/v2"
    ctgov_requests_per_minute: int = 40  # stay under the documented ~50 req/min guidance
    ctgov_timeout_seconds: float = 20.0
    trial_cache_ttl_hours: int = 24
    snapshot_path: Path = BACKEND_DIR / "data" / "snapshots" / "ctgov_lpa_snapshot.json"

    # LLM (optional)
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_enabled: bool = False

    @field_validator("document_encryption_key", "anthropic_api_key", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, v):
        # `KEY=` in an .env file means "not configured", not an empty secret.
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_enabled and self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
