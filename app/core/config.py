"""Configurações da aplicação lidas de variáveis de ambiente (.env)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Aplicação
    APP_NAME: str = "Foco Policial API"
    APP_ENV: str = Field(default="development")  # development | staging | production
    DEBUG: bool = Field(default=False)
    API_V1_PREFIX: str = "/api/v1"

    # Banco de dados (Supabase usado apenas como Postgres gerenciado — sem Auth/RLS)
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/foco_policial"
    )
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Redis (cache, rate limiting)
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Segurança / JWT
    JWT_SECRET_KEY: str = Field(default="changeme-in-env-never-commit")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # CORS
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60


@lru_cache
def get_settings() -> Settings:
    """Settings em cache — lida do ambiente uma única vez por processo."""
    return Settings()


settings = get_settings()
