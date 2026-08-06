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

    # Recuperação de senha
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60
    # URL base do frontend, usada para montar o link enviado por e-mail
    # (ex.: {FRONTEND_URL}/redefinir-senha?token=...).
    FRONTEND_URL: str = Field(default="http://localhost:3000")

    # E-mail transacional
    # EMAIL_DRIVER=console (padrão): apenas loga o e-mail formatado — não exige
    # nenhuma infra externa, ideal para desenvolvimento e para novos ambientes
    # até que um provedor SMTP seja configurado.
    # EMAIL_DRIVER=smtp: envia de fato via SMTP (qualquer provedor: SES, Postmark,
    # Resend, Mailgun, Gmail etc. — todos falam SMTP) usando as credenciais abaixo.
    EMAIL_DRIVER: str = Field(default="console")  # console | smtp
    SMTP_HOST: str = Field(default="")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_USE_TLS: bool = Field(default=True)
    SMTP_FROM_EMAIL: str = Field(default="no-reply@focopolicial.com.br")
    SMTP_FROM_NAME: str = Field(default="Foco Policial")

    # Worker de agregação de analytics (app/workers/analytics_aggregator.py),
    # agendado in-process via APScheduler — ver app/core/scheduler.py.
    # Só é seguro com a API rodando como processo único (ver docstring de
    # app/core/scheduler.py antes de escalar para múltiplas instâncias).
    ANALYTICS_AGGREGATOR_ENABLED: bool = Field(default=True)
    # Frequência do job "rápido" (janela de 2 dias, mantém o dashboard quase
    # em tempo real). Recomendação original: 5-15 min.
    ANALYTICS_AGGREGATOR_INTERVAL_MINUTES: int = Field(default=10, ge=1)
    # Hora (UTC) do job diário de reconciliação, janela maior.
    ANALYTICS_AGGREGATOR_DAILY_HOUR_UTC: int = Field(default=3, ge=0, le=23)
    ANALYTICS_AGGREGATOR_DAILY_WINDOW_DAYS: int = Field(default=30, ge=1)

    # CORS
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60


@lru_cache
def get_settings() -> Settings:
    """Settings em cache — lida do ambiente uma única vez por processo."""
    return Settings()


settings = get_settings()