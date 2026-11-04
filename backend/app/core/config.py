from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
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

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def empty_jwt_secret(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def require_deployed_jwt_secret(self) -> "Settings":
        if self.env in (Env.STAGING, Env.PRODUCTION) and self.jwt_secret is None:
            raise ValueError("Для staging и production необходимо задать JWT_SECRET")
        return self

    def redis_dsn(self, db: int) -> str:
        return f"{self.redis_url.rstrip('/')}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
