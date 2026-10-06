"""All runtime configuration comes from the environment. Secrets never live in the repository."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineMode(StrEnum):
    # Phases 1-2: every report is transcribed and tagged by a person. No model is called.
    MANUAL = "manual"
    # Phase 3+: workers call the model service; anything below threshold still goes to a person.
    ASSISTED = "assisted"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JAMII_", env_file=".env", extra="ignore")

    environment: str = "local"  # local | staging | production
    secret_key: str = Field(default="dev-only-session-and-token-key-change-me", min_length=32)
    # Separate key for pseudonyms so rotating the session key does not change how CHPs appear.
    pseudonym_key: str = Field(default="dev-only-pseudonym-key-change-me-too", min_length=32)
    base_url: str = "http://localhost:8000"

    database_url: str = "postgresql+psycopg://jamii:jamii@localhost:5432/jamii"
    # The audit log lives in its own database so nobody editing reports can edit the trail.
    audit_database_url: str = "postgresql+psycopg://jamii_audit:jamii_audit@localhost:5432/jamii_audit"
    redis_url: str = "redis://localhost:6379/0"
    # When false (or Redis is unreachable) the API does the work inline instead of queueing it.
    queue_enabled: bool = True

    storage_backend: str = "minio"  # minio | local
    storage_local_dir: str = "./var/audio"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "jamii"
    minio_secret_key: str = "jamii-dev-secret"
    minio_bucket: str = "voice-notes"
    minio_secure: bool = False

    sms_backend: str = "console"  # console | africastalking
    at_username: str = "sandbox"
    at_api_key: str = ""
    at_sender_id: str = ""  # leave empty to use the shared short code
    at_sandbox: bool = True
    # Africa's Talking does not sign callbacks; callbacks must carry this token.
    channel_callback_token: str = "dev-callback-token"
    ussd_service_code: str = "*384*1234#"

    pipeline_mode: PipelineMode = PipelineMode.MANUAL
    model_service_url: str = "http://localhost:8100"
    model_service_timeout_s: float = 20.0
    # Thresholds are set from pilot data (see ml/scripts/thresholds.py). Above 1.0 means
    # "never auto-accept": the model only pre-fills suggestions for the reviewer.
    transcribe_min_confidence: float = 1.01
    classify_min_confidence: float = 1.01
    # The named-entity redaction pass runs only once its model has passed evaluation.
    ner_redaction_enabled: bool = False
    recheck_sample_size: int = 30
    spike_alerts_enabled: bool = False

    audio_retention_days: int = 30
    text_retention_days: int = 730
    otp_ttl_seconds: int = 300
    otp_max_requests: int = 3  # per phone per otp_request_window
    otp_request_window_minutes: int = 15
    otp_max_failed_attempts: int = 5  # per phone per lockout window
    lockout_minutes: int = 30
    mobile_token_days: int = 30
    session_hours: int = 12
    max_reports_per_hour: int = 30
    max_audio_bytes: int = 3_000_000
    max_text_chars: int = 2000

    issue_default_level: str = "cha"
    consent_version: str = "2026-10-v1"

    sentry_dsn: str = ""
    # Shows one-time codes on the login page. Refused outside local development.
    dev_show_otp: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment != "local":
        if settings.secret_key.startswith("dev-") or settings.pseudonym_key.startswith("dev-"):
            raise RuntimeError("Set JAMII_SECRET_KEY and JAMII_PSEUDONYM_KEY outside local development")
        if settings.dev_show_otp:
            raise RuntimeError("JAMII_DEV_SHOW_OTP is only allowed in local development")
    return settings
