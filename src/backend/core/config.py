"""
Backend System Configuration & Security Environment Settings.
"""
from typing import List
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Server & Environment
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    app_port: int = Field(default=8000)
    app_host: str = Field(default="0.0.0.0")
    cors_allowed_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./sales_ai_dev.db",
        description="Async database connection string"
    )
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "sales_ai_db"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres_dev_password_change_in_prod"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = "redis_dev_password"

    # Security & Tokens
    jwt_secret_key: str = Field(
        default="dev_jwt_secret_key_minimum_32_characters_random_change_in_prod",
        min_length=32
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    enforce_mfa_for_managers: bool = True
    mfa_encryption_key: str = Field(
        default="sales_ai_mfa_dev_master_key_32_bytes_min_length_secret!",
        min_length=32,
        description="Master key used to encrypt TOTP MFA seeds at rest"
    )

    # S3 Object Storage
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minio_dev_access_key"
    s3_secret_key: str = "minio_dev_secret_key"
    s3_bucket_documents: str = "sales-ai-documents"
    s3_bucket_recordings: str = "sales-ai-recordings"

    # Data Retention
    data_retention_days_audio: int = 90
    data_retention_days_transcripts: int = 365
    pii_redaction_enabled: bool = True

    # Omnichannel Webhooks & Integrations
    whatsapp_webhook_secret: str = "dev_whatsapp_webhook_secret_change_in_prod"
    whatsapp_verify_token: str = "dev_whatsapp_verify_token_12345"
    email_webhook_secret: str = "dev_email_webhook_secret_change_in_prod"
    voice_telephony_secret: str = "dev_telephony_secret_change_in_prod"
    webchat_shared_token: str = "dev_webchat_token_change_in_prod"

    # Payments: development-only fallback. Production secrets are stored per tenant in
    # tenant_channel_integrations (channel_type 'PAYMENT_<PROVIDER>').
    payment_webhook_secret: str = "dev_payment_webhook_secret_change_in_prod"
    payment_webhook_tolerance_seconds: int = 300

    # Signs short-lived customer voice session tokens (tenant + session binding).
    voice_session_secret: str = Field(
        default="dev_voice_session_signing_secret_change_in_prod_32b",
        min_length=32
    )
    voice_session_token_ttl_seconds: int = 3600

    # Signs public quote acceptance/rejection links (F-14).
    quote_link_secret: str = Field(default="dev_quote_link_signing_secret_change_in_prod_32b", min_length=32)
    quote_link_ttl_days: int = 45

    # Load the primary LLM at startup so the first customer turn does not pay the
    # measured ~15 s cold start (F-16).
    ai_warmup_on_startup: bool = False

    # Peripheral n8n outbound signing secret.
    n8n_webhook_secret: str = "dev_n8n_webhook_secret_change_in_prod"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in DEVELOPMENT_ENVIRONMENTS

    @model_validator(mode="after")
    def _reject_insecure_defaults_outside_development(self) -> "Settings":
        """
        F-10: Committed development defaults must never reach a non-development deployment.
        Fails startup when any secret still equals its committed default, or when the
        database is SQLite (no Row-Level Security).
        """
        if self.is_development:
            return self
        problems = [
            name for name in SECRET_FIELDS
            if getattr(self, name) == type(self).model_fields[name].default
        ]
        if self.database_url.startswith("sqlite"):
            problems.append("database_url (SQLite has no Row-Level Security)")
        if problems:
            raise ValueError(
                f"Refusing to start in environment '{self.environment}': insecure default "
                f"configuration for {', '.join(problems)}. Provide real values via environment/secret store."
            )
        return self


DEVELOPMENT_ENVIRONMENTS = {"development", "dev", "test", "testing", "local"}

SECRET_FIELDS = (
    "postgres_password", "redis_password", "jwt_secret_key", "mfa_encryption_key",
    "s3_access_key", "s3_secret_key", "whatsapp_webhook_secret", "whatsapp_verify_token",
    "email_webhook_secret", "voice_telephony_secret", "webchat_shared_token",
    "payment_webhook_secret", "voice_session_secret", "n8n_webhook_secret", "quote_link_secret",
)

settings = Settings()
