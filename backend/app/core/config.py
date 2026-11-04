from enum import StrEnum
from functools import lru_cache

from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    env: Env = Env.LOCAL
    debug: bool = False
    app_name: str = "Идеальный День"
    api_prefix: str = "/api/v1"

    cors_origins: list[str] = ["http://localhost:5173"]

    database_url: str = "postgresql+asyncpg://perfectday:perfectday@localhost:5432/perfectday"

    redis_url: str = "redis://localhost:6379"
    redis_cache_db: int = 0
    redis_broker_db: int = 1
    redis_result_db: int = 2

    jwt_secret: SecretStr | None = Field(default=None, min_length=32)
    access_ttl_min: int = Field(default=15, gt=0)
    refresh_ttl_days: int = Field(default=30, gt=0)
    email_verification_ttl_hours: int = Field(default=24, gt=0)
    password_reset_ttl_min: int = Field(default=60, gt=0)
    frontend_url: AnyHttpUrl = AnyHttpUrl("http://localhost:5173")
    refresh_cookie_secure: bool | None = None
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_from: EmailStr = "noreply@example.com"
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = False
    smtp_ssl_tls: bool = False

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def empty_jwt_secret(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def require_deployed_jwt_secret(self) -> "Settings":
        if self.env in (Env.STAGING, Env.PRODUCTION) and self.jwt_secret is None:
            raise ValueError("Для staging и production необходимо задать JWT_SECRET")
        return self

    @model_validator(mode="after")
    def validate_auth_transport(self) -> "Settings":
        if self.smtp_starttls and self.smtp_ssl_tls:
            raise ValueError("SMTP_STARTTLS и SMTP_SSL_TLS нельзя включать одновременно")
        if self.frontend_url.query or self.frontend_url.fragment:
            raise ValueError("FRONTEND_URL не должен содержать query или fragment")
        if self.frontend_url.username or self.frontend_url.password:
            raise ValueError("FRONTEND_URL не должен содержать учётные данные")
        if self.env in (Env.STAGING, Env.PRODUCTION):
            if self.refresh_cookie_secure is False:
                raise ValueError("На staging и production refresh-cookie требует Secure")
            if self.frontend_url.scheme != "https":
                raise ValueError("На staging и production FRONTEND_URL должен использовать HTTPS")
        return self

    @property
    def secure_refresh_cookie(self) -> bool:
        if self.refresh_cookie_secure is not None:
            return self.refresh_cookie_secure
        return self.env in (Env.STAGING, Env.PRODUCTION)

    def redis_dsn(self, db: int) -> str:
        return f"{self.redis_url.rstrip('/')}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
