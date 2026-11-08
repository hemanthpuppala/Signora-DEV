"""Application configuration (backbone LLD, topic 6).

One read-only settings object per process. Values come from process environment variables, then
the repository's ``.env`` file, then defaults in code. The flat variable names of ``.env`` are
validated by ``_EnvVars`` and then grouped into small frozen models, so each module receives only
its own group.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_VAR = "SIGNORA_ROOT"
ROOT_MARKER = ".env.example"
MIN_SECRET_KEY_LENGTH = 32
# kernel/config.py -> kernel -> signora -> src -> api -> apps -> <repository root>
_DERIVED_ROOT_DEPTH = 5

AppEnv = Literal["development", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
EmailProvider = Literal["sendgrid", "smtp", "mailpit"]
RateLimiterBackend = Literal["memory"]  # "redis" is added together with its implementation
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]


class ConfigError(Exception):
    """Raised when configuration cannot be loaded. Lists every problem at once."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        message = "Invalid configuration:\n" + "\n".join(f"  - {p}" for p in problems)
        super().__init__(message)


def repo_root() -> Path:
    """Return the repository root.

    ``SIGNORA_ROOT`` wins when set (container images set it). Otherwise the root is derived from
    this file's location. Either way it must contain the marker file, so a wrong root fails loudly.
    """
    explicit = os.environ.get(ROOT_ENV_VAR)
    if explicit:
        root = Path(explicit).expanduser().resolve()
        source = f"{ROOT_ENV_VAR}={explicit}"
    else:
        root = Path(__file__).resolve().parents[_DERIVED_ROOT_DEPTH]
        source = "derived from the package location"
    if not (root / ROOT_MARKER).is_file():
        raise ConfigError(
            [f"repository root {root} ({source}) lacks {ROOT_MARKER}; set {ROOT_ENV_VAR}"]
        )
    return root


class _EnvVars(BaseSettings):
    """Every configuration variable, by its flat name. ``.env.example`` documents exactly these."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_ignore_empty=True,  # `AI_API_KEY=` in .env means "not set"
        extra="ignore",  # .env also carries compose-only values; unknown keys are not errors
        frozen=True,
    )

    # app
    app_env: AppEnv = "development"
    public_base_url: AnyHttpUrl
    secret_key: SecretStr
    log_level: LogLevel = "INFO"
    signora_commit: str = "dev"
    api_threads: int = Field(default=20, ge=1, le=200)
    # Trust X-Request-ID / X-Forwarded-For only when the API is reachable solely through the proxy.
    api_trust_proxy_headers: bool = False
    # database
    postgres_host: str
    postgres_port: int = Field(ge=1, le=65535)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr = Field(min_length=1)
    postgres_db: str = Field(min_length=1)
    # blob store
    # "s3" is added together with its implementation (LLD topic 5)
    blob_store_backend: Literal["local"] = "local"
    blob_store_dir: Path = Path("./data/blobs")
    # gotenberg
    gotenberg_host: str
    gotenberg_port: int = Field(ge=1, le=65535)
    # documents (Phase 4 LLD topic 2)
    document_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=500 * 1024 * 1024)
    document_max_pages: int = Field(default=200, ge=1, le=2000)
    document_uploads_per_hour: int = Field(default=60, ge=1, le=10_000)
    # signing defaults
    signing_otp_ttl_minutes: int = Field(default=10, ge=1, le=60)
    signing_otp_max_attempts: int = Field(default=5, ge=1, le=20)
    signer_session_minutes: int = Field(default=30, ge=5, le=240)
    default_reminder_interval_hours: int = Field(default=24, ge=1, le=24 * 30)
    default_max_reminders: int = Field(default=5, ge=0, le=20)  # departments allow 0-20
    default_expiry_days: int = Field(default=14, ge=1, le=365)
    # worker
    worker_concurrency: int = Field(default=8, ge=1, le=64)
    # ai (integration)
    ai_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    ai_api_key: SecretStr | None = None
    ai_model: str = "gpt-6-luna"
    ai_reasoning_effort: ReasoningEffort = "medium"
    ai_whole_doc_max_tokens: int = Field(default=40_000, ge=1_000)
    ai_max_concurrency: int = Field(default=4, ge=1, le=32)
    # email (integration)
    email_provider: EmailProvider = "smtp"
    sendgrid_api_key: SecretStr | None = None
    mailpit_host: str = "127.0.0.1"
    mailpit_smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_starttls: bool = True
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    email_from_address: EmailStr | None = None
    email_from_name: str = "Signora"
    email_daily_limit: int = Field(default=450, ge=1)
    # accounts and sessions (Phase 2 LLD)
    auth_session_idle_hours: int = Field(default=12, ge=1, le=24 * 30)
    auth_session_touch_minutes: int = Field(default=5, ge=1, le=60)
    auth_signup_link_hours: int = Field(default=24, ge=1, le=24 * 7)
    auth_reset_link_minutes: int = Field(default=30, ge=5, le=24 * 60)
    auth_invite_days: int = Field(default=7, ge=1, le=30)
    auth_email_cooldown_seconds: int = Field(default=60, ge=0, le=3600)
    auth_email_hourly_limit: int = Field(default=5, ge=1, le=100)
    auth_invites_per_hour: int = Field(default=50, ge=1, le=10_000)
    auth_login_free_attempts: int = Field(default=5, ge=1, le=50)
    auth_login_backoff_cap_minutes: int = Field(default=15, ge=1, le=24 * 60)
    auth_login_ip_limit: int = Field(default=100, ge=1, le=100_000)
    auth_login_ip_window_minutes: int = Field(default=15, ge=1, le=24 * 60)
    auth_password_min_length: int = Field(default=12, ge=8, le=64)
    # rate limiting
    rate_limiter_backend: RateLimiterBackend = "memory"
    rate_limiter_max_keys: int = Field(default=100_000, ge=1_000, le=10_000_000)
    # stripe (optional; only needed to offer ID verification)
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None

    @field_validator("secret_key")
    @classmethod
    def _secret_key_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(f"must be at least {MIN_SECRET_KEY_LENGTH} characters")
        return value

    @model_validator(mode="after")
    def _production_rules(self) -> _EnvVars:
        if self.app_env != "production":
            return self
        problems: list[str] = []
        if self.public_base_url.scheme != "https":
            problems.append("PUBLIC_BASE_URL: must use https in production")
        if self.ai_api_key is None:
            problems.append("AI_API_KEY: required in production")
        if self.email_provider == "mailpit":
            problems.append(
                "EMAIL_PROVIDER: 'mailpit' only captures mail; use 'sendgrid' or 'smtp'"
            )
        required = {
            "sendgrid": ("sendgrid_api_key", "email_from_address"),
            "smtp": ("smtp_username", "smtp_password", "email_from_address"),
            "mailpit": (),
        }[self.email_provider]
        for name in required:
            if getattr(self, name) is None:
                problems.append(f"{name.upper()}: required in production")
        if problems:
            raise ValueError("; ".join(problems))
        return self


# --- Grouped, read-only settings handed to modules ---------------------------------------------


class _Group(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AppSettings(_Group):
    env: AppEnv
    public_base_url: AnyHttpUrl
    secret_key: SecretStr
    log_level: LogLevel
    commit: str
    root: Path

    @property
    def is_production(self) -> bool:
        return self.env == "production"


class ApiSettings(_Group):
    threads: int
    trust_proxy_headers: bool


class DatabaseSettings(_Group):
    host: str
    port: int
    user: str
    password: SecretStr
    name: str

    @property
    def url(self) -> str:
        """SQLAlchemy URL built from the parts; never stored as a separate variable.

        Built with ``URL.create`` so a user or password containing ``@``, ``/``, ``#`` or ``%`` is
        percent-encoded instead of breaking the URL.
        """
        from sqlalchemy import URL

        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        ).render_as_string(hide_password=False)

    @property
    def conninfo(self) -> str:
        """libpq connection string for direct psycopg connections (e.g. LISTEN)."""
        from psycopg.conninfo import make_conninfo

        return make_conninfo(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password.get_secret_value(),
            dbname=self.name,
            application_name="signora",
        )


class BlobStoreSettings(_Group):
    backend: Literal["local"]
    dir: Path  # absolute: resolved against the repository root


class DocumentSettings(_Group):
    max_bytes: int
    max_pages: int
    uploads_per_hour: int


class GotenbergSettings(_Group):
    host: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class SigningSettings(_Group):
    otp_ttl_minutes: int
    otp_max_attempts: int
    session_minutes: int
    default_reminder_interval_hours: int
    default_max_reminders: int
    default_expiry_days: int


class WorkerSettings(_Group):
    concurrency: int


class AISettings(_Group):
    base_url: AnyHttpUrl
    api_key: SecretStr | None
    model: str
    reasoning_effort: ReasoningEffort
    whole_doc_max_tokens: int
    max_concurrency: int

    @property
    def configured(self) -> bool:
        return self.api_key is not None


class EmailSettings(_Group):
    provider: EmailProvider
    sendgrid_api_key: SecretStr | None
    mailpit_host: str
    mailpit_smtp_port: int
    smtp_host: str
    smtp_port: int
    smtp_starttls: bool
    smtp_username: str | None
    smtp_password: SecretStr | None
    from_address: str | None
    from_name: str
    daily_limit: int

    @property
    def configured(self) -> bool:
        if self.from_address is None:
            return False
        if self.provider == "mailpit":
            return True
        if self.provider == "sendgrid":
            return self.sendgrid_api_key is not None
        return self.smtp_username is not None and self.smtp_password is not None


class AuthSettings(_Group):
    """Accounts, sessions and their limits (Phase 2 LLD). Durations are kept in their .env units."""

    session_idle_hours: int
    session_touch_minutes: int
    signup_link_hours: int
    reset_link_minutes: int
    invite_days: int
    email_cooldown_seconds: int
    email_hourly_limit: int
    invites_per_hour: int
    login_free_attempts: int
    login_backoff_cap_minutes: int
    login_ip_limit: int
    login_ip_window_minutes: int
    password_min_length: int


class RateLimitSettings(_Group):
    backend: RateLimiterBackend
    max_keys: int


class StripeSettings(_Group):
    secret_key: SecretStr | None
    webhook_secret: SecretStr | None

    @property
    def configured(self) -> bool:
        return self.secret_key is not None and self.webhook_secret is not None


class Settings(_Group):
    app: AppSettings
    api: ApiSettings
    db: DatabaseSettings
    blob_store: BlobStoreSettings
    gotenberg: GotenbergSettings
    documents: DocumentSettings
    signing: SigningSettings
    worker: WorkerSettings
    ai: AISettings
    email: EmailSettings
    auth: AuthSettings
    rate_limit: RateLimitSettings
    stripe: StripeSettings


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def _format_errors(error: ValidationError) -> list[str]:
    problems: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]).upper()
        message = item["msg"].removeprefix("Value error, ")
        problems.extend(
            message.split("; ") if not location else [f"{location}: {message}"],
        )
    return problems


def load_settings(root: Path | None = None) -> Settings:
    """Load and validate settings for the given repository root (the real root by default).

    Raises ``ConfigError`` listing every problem when any value is missing or invalid.
    """
    base = root if root is not None else repo_root()
    try:
        env = _EnvVars(_env_file=base / ".env")
    except ValidationError as error:
        raise ConfigError(_format_errors(error)) from None

    return Settings(
        app=AppSettings(
            env=env.app_env,
            public_base_url=env.public_base_url,
            secret_key=env.secret_key,
            log_level=env.log_level,
            commit=env.signora_commit,
            root=base,
        ),
        api=ApiSettings(threads=env.api_threads, trust_proxy_headers=env.api_trust_proxy_headers),
        db=DatabaseSettings(
            host=env.postgres_host,
            port=env.postgres_port,
            user=env.postgres_user,
            password=env.postgres_password,
            name=env.postgres_db,
        ),
        blob_store=BlobStoreSettings(
            backend=env.blob_store_backend, dir=_resolve(base, env.blob_store_dir)
        ),
        gotenberg=GotenbergSettings(host=env.gotenberg_host, port=env.gotenberg_port),
        documents=DocumentSettings(
            max_bytes=env.document_max_bytes,
            max_pages=env.document_max_pages,
            uploads_per_hour=env.document_uploads_per_hour,
        ),
        signing=SigningSettings(
            otp_ttl_minutes=env.signing_otp_ttl_minutes,
            otp_max_attempts=env.signing_otp_max_attempts,
            session_minutes=env.signer_session_minutes,
            default_reminder_interval_hours=env.default_reminder_interval_hours,
            default_max_reminders=env.default_max_reminders,
            default_expiry_days=env.default_expiry_days,
        ),
        worker=WorkerSettings(concurrency=env.worker_concurrency),
        ai=AISettings(
            base_url=env.ai_base_url,
            api_key=env.ai_api_key,
            model=env.ai_model,
            reasoning_effort=env.ai_reasoning_effort,
            whole_doc_max_tokens=env.ai_whole_doc_max_tokens,
            max_concurrency=env.ai_max_concurrency,
        ),
        email=EmailSettings(
            provider=env.email_provider,
            sendgrid_api_key=env.sendgrid_api_key,
            mailpit_host=env.mailpit_host,
            mailpit_smtp_port=env.mailpit_smtp_port,
            smtp_host=env.smtp_host,
            smtp_port=env.smtp_port,
            smtp_starttls=env.smtp_starttls,
            smtp_username=env.smtp_username,
            smtp_password=env.smtp_password,
            from_address=env.email_from_address,
            from_name=env.email_from_name,
            daily_limit=env.email_daily_limit,
        ),
        auth=AuthSettings(
            session_idle_hours=env.auth_session_idle_hours,
            session_touch_minutes=env.auth_session_touch_minutes,
            signup_link_hours=env.auth_signup_link_hours,
            reset_link_minutes=env.auth_reset_link_minutes,
            invite_days=env.auth_invite_days,
            email_cooldown_seconds=env.auth_email_cooldown_seconds,
            email_hourly_limit=env.auth_email_hourly_limit,
            invites_per_hour=env.auth_invites_per_hour,
            login_free_attempts=env.auth_login_free_attempts,
            login_backoff_cap_minutes=env.auth_login_backoff_cap_minutes,
            login_ip_limit=env.auth_login_ip_limit,
            login_ip_window_minutes=env.auth_login_ip_window_minutes,
            password_min_length=env.auth_password_min_length,
        ),
        rate_limit=RateLimitSettings(
            backend=env.rate_limiter_backend, max_keys=env.rate_limiter_max_keys
        ),
        stripe=StripeSettings(
            secret_key=env.stripe_secret_key, webhook_secret=env.stripe_webhook_secret
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings for this process, loaded once."""
    return load_settings()


def env_var_names() -> frozenset[str]:
    """Names of every configuration variable (used to keep ``.env.example`` in sync)."""
    return frozenset(name.upper() for name in _EnvVars.model_fields)
