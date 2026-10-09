"""All runtime configuration comes from the environment. Secrets never live in the repository."""

from enum import StrEnum
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineMode(StrEnum):
    # Phases 1-2: every report is transcribed and tagged by a person. No model is called.
    MANUAL = "manual"
    # Phase 3+: workers call the model service; anything below threshold still goes to a person.
    ASSISTED = "assisted"


# Query parameters some providers add for other client libraries; libpq rejects them.
_FOREIGN_URL_PARAMS = {"supa", "pgbouncer", "workaround"}


def with_psycopg_driver(url: str) -> str:
    """Providers hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix) :]
            break
    parts = urlsplit(url)
    if parts.query:
        kept = [(k, v) for k, v in parse_qsl(parts.query) if k not in _FOREIGN_URL_PARAMS]
        url = urlunsplit(parts._replace(query=urlencode(kept)))
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JAMII_", env_file=".env", extra="ignore")

    environment: str = "local"  # local | staging | production
    secret_key: str = Field(default="dev-only-session-and-token-key-change-me", min_length=32)
    # Separate key for pseudonyms so rotating the session key does not change how CHPs appear.
    pseudonym_key: str = Field(default="dev-only-pseudonym-key-change-me-too", min_length=32)
    base_url: str = "http://localhost:8000"
    # Browser origins allowed to call the CHP API (the Flutter app built for the web), as a
    # JSON list. Local development also allows any http://localhost port.
    cors_origins: list[str] = []

    # Hosted Postgres injects its own names: POSTGRES_URL (Supabase's Vercel integration, the
    # transaction pooler) or DATABASE_URL. A JAMII_ variable always wins.
    database_url: str = Field(
        default="postgresql+psycopg://jamii:jamii@localhost:5432/jamii",
        validation_alias=AliasChoices("JAMII_DATABASE_URL", "POSTGRES_URL", "DATABASE_URL"),
    )
    # The audit log lives in its own database so nobody editing reports can edit the trail.
    # On a single hosted database (Supabase on Vercel) it shares the main one.
    audit_database_url: str = Field(
        default="postgresql+psycopg://jamii_audit:jamii_audit@localhost:5432/jamii_audit",
        validation_alias=AliasChoices("JAMII_AUDIT_DATABASE_URL", "POSTGRES_URL", "DATABASE_URL"),
    )
    # Migrations take a session-level lock, so they need a session (not transaction) pooler or a
    # direct connection: Supabase's POSTGRES_URL_NON_POOLING (port 5432).
    migration_database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "JAMII_MIGRATION_DATABASE_URL", "POSTGRES_URL_NON_POOLING", "DATABASE_URL_UNPOOLED"
        ),
    )
    # Serverless hosting has no release step: migrate on cold start, under a lock.
    auto_migrate: bool = False
    # Creates the first admin on start-up if there is no admin yet. Everyone else is added in Admin.
    bootstrap_admin_phone: str = ""
    bootstrap_admin_name: str = "Administrator"
    # If set, /metrics needs "Authorization: Bearer <token>" (for hosts without a private network).
    metrics_token: str = ""
    redis_url: str = "redis://localhost:6379/0"
    # When false (or Redis is unreachable) the API does the work inline instead of queueing it.
    queue_enabled: bool = True

    storage_backend: str = "minio"  # minio | supabase | local
    storage_local_dir: str = "./var/audio"
    # Supabase Storage (the Vercel deployment). Supabase's Vercel integration sets the URL and key.
    supabase_url: str = Field(default="", validation_alias=AliasChoices("JAMII_SUPABASE_URL", "SUPABASE_URL"))
    supabase_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("JAMII_SUPABASE_SECRET_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    supabase_bucket: str = "voice-notes"
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
    # Public demo with synthetic data (the Vercel deployment): shows a banner and the demo
    # logins, puts one-time codes on screen, and never sends a real SMS.
    demo_mode: bool = False

    @field_validator("database_url", "audit_database_url", "migration_database_url")
    @classmethod
    def _psycopg_driver(cls, url: str | None) -> str | None:
        return with_psycopg_driver(url) if url else url

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def shows_codes_on_screen(self) -> bool:
        return self.demo_mode or (self.dev_show_otp and self.environment == "local")

    def check(self) -> None:
        """Refuse unsafe combinations before serving anything."""
        if self.environment != "local":
            if self.secret_key.startswith("dev-") or self.pseudonym_key.startswith("dev-"):
                raise RuntimeError("Set JAMII_SECRET_KEY and JAMII_PSEUDONYM_KEY outside local development")
            if self.dev_show_otp:
                raise RuntimeError("JAMII_DEV_SHOW_OTP is only allowed in local development")
        if self.demo_mode:
            if self.is_production:
                raise RuntimeError("JAMII_DEMO_MODE is never allowed in production")
            if self.sms_backend != "console":
                raise RuntimeError("A demo never sends real SMS: set JAMII_SMS_BACKEND=console")
        if self.is_production and self.sms_backend == "console":
            raise RuntimeError("Production sends real SMS: set JAMII_SMS_BACKEND=africastalking")
        if self.sms_backend == "africastalking" and not self.at_api_key and self.environment != "local":
            raise RuntimeError("Set JAMII_AT_USERNAME and JAMII_AT_API_KEY to send SMS through Africa's Talking")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check()
    return settings
