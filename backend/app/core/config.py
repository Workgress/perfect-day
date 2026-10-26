from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Env = Env.LOCAL
    app_name: str = "Идеальный День"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://perfectday:perfectday@localhost:5432/perfectday"

    redis_url: str = "redis://localhost:6379"
    redis_cache_db: int = 0
    redis_broker_db: int = 1
    redis_result_db: int = 2

    def redis_dsn(self, db: int) -> str:
        return f"{self.redis_url.rstrip('/')}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
