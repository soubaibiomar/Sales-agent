"""
Backend System Configuration & Security Environment Settings.
"""
from typing import List
from pydantic import Field
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

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

settings = Settings()
