"""Configurações da aplicação lidas de variáveis de ambiente (.env)."""

from functools import lru_cache

from pydantic import Field, model_validator
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

    # Worker de renovação automática de assinaturas
    # (app/workers/subscription_renewal.py, PROMPT 10), agendado in-process
    # via APScheduler — mesmo padrão de ANALYTICS_AGGREGATOR_*, ver
    # app/core/scheduler.py. Só é seguro com a API rodando como processo
    # único (mesma ressalva de escala horizontal do agregador de analytics).
    SUBSCRIPTION_RENEWAL_ENABLED: bool = Field(default=True)
    # Frequência do job: cobra assinaturas ATIVA cujo período já terminou e
    # efetiva cancelamentos agendados vencidos. Não precisa rodar com alta
    # frequência (diferente do analytics, que alimenta um dashboard quase
    # em tempo real) — o requisito é só não deixar o período vencido sem
    # cobrança por muito tempo.
    SUBSCRIPTION_RENEWAL_INTERVAL_MINUTES: int = Field(default=60, ge=1)

    # Worker de dunning (app/workers/subscription_dunning.py, PROMPT 11,
    # roadmap item 11), agendado in-process via APScheduler — mesmo padrão
    # de SUBSCRIPTION_RENEWAL_*/ANALYTICS_AGGREGATOR_*, ver
    # app/core/scheduler.py. Só é seguro com a API rodando como processo
    # único (mesma ressalva de escala horizontal dos demais workers).
    #
    # Política comercial (decidida explicitamente pelo usuário nesta sessão,
    # não inventada — ver docs/DECISIONS.md ADR-027): 3 tentativas de
    # recobrança, uma por dia, dentro de um grace period de 3 dias — ou
    # seja, o grace period e o intervalo x tentativas coincidem por
    # construção (3 x 1 dia = 3 dias). Mudar um sem o outro é uma decisão
    # de negócio válida (ex.: grace period maior que tentativas x intervalo
    # só significa que a assinatura fica alguns dias sem nova tentativa
    # antes de expirar) — os três valores são independentes no código.
    DUNNING_ENABLED: bool = Field(default=True)
    # Frequência do job: procura assinaturas INADIMPLENTE com retry
    # elegível ou grace period vencido. Mesmo raciocínio de
    # SUBSCRIPTION_RENEWAL_INTERVAL_MINUTES — não precisa de alta
    # frequência, só não deixar uma tentativa elegível esperando demais.
    DUNNING_INTERVAL_MINUTES: int = Field(default=60, ge=1)
    # Número máximo de tentativas de recobrança por ciclo de inadimplência.
    DUNNING_MAX_RETRIES: int = Field(default=3, ge=1)
    # Intervalo entre tentativas de recobrança, em dias.
    DUNNING_RETRY_INTERVAL_DAYS: int = Field(default=1, ge=1)
    # Duração do grace period (INADIMPLENTE -> EXPIRADA), em dias, a partir
    # do momento em que a assinatura entra em INADIMPLENTE.
    DUNNING_GRACE_PERIOD_DAYS: int = Field(default=3, ge=1)

    # CORS
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # Políticas dedicadas para rotas sensíveis a abuso (força bruta,
    # enumeração de contas, flood de webhook/checkout). Cada uma é contada
    # isoladamente por IP e por janela de 60s — não compartilham o balde da
    # política padrão (`RATE_LIMIT_PER_MINUTE`) nem entre si.
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_REGISTER_PER_MINUTE: int = 5
    RATE_LIMIT_FORGOT_PASSWORD_PER_MINUTE: int = 3
    RATE_LIMIT_RESET_PASSWORD_PER_MINUTE: int = 5
    RATE_LIMIT_BILLING_PER_MINUTE: int = 20

    # Comportamento explícito quando o Redis está indisponível (ou quando
    # `request.app.state.redis` não existe). Antes desta mudança, a falha
    # era engolida em silêncio (`except Exception: pass`), sem log e sem
    # decisão declarada.
    #
    # True (padrão): "fail open" — a requisição prossegue sem limite
    # aplicado. Prioriza disponibilidade (inclusive de login) sobre a
    # proteção de rate limit quando a infra de cache está fora do ar. O
    # evento é sempre logado como warning estruturado para alerta
    # operacional (ver PROJECT_STATE.md §15 — observabilidade).
    #
    # False: "fail closed" — a requisição é bloqueada com 503 enquanto o
    # Redis estiver indisponível. Prioriza proteção contra abuso sobre
    # disponibilidade. Só ative se o negócio decidir que abuso sem rate
    # limit é pior do que indisponibilidade parcial.
    RATE_LIMIT_FAIL_OPEN: bool = True


    # Billing — gateway de pagamento (ver app/services/billing/gateway.py)
    # PAYMENT_GATEWAY_DRIVER=console (padrão): nenhum provedor real — aprova
    # toda cobrança imediatamente via ConsoleGateway. Usar apenas em
    # desenvolvimento/teste. Quando um provedor real for integrado, este
    # campo passa a selecionar o driver correspondente (ex.: "stripe").
    PAYMENT_GATEWAY_DRIVER: str = Field(default="console")  # console | (futuro: stripe, etc.)
    # Segredo compartilhado com o provedor de pagamento, usado para validar a
    # assinatura do payload recebido em app/api/v1/billing/webhooks.py,
    # verificada pelo driver configurado (ver
    # app/services/billing/gateway.py::PaymentGateway.parse_webhook_event,
    # ADR-016). Deve ficar vazio apenas quando PAYMENT_GATEWAY_DRIVER=
    # "console" — ver validação abaixo, que impede subir em produção com um
    # driver real e sem segredo configurado.
    PAYMENT_WEBHOOK_SECRET: str = Field(default="")

    

    @model_validator(mode="after")
    def _validate_production_webhook_secret(self) -> "Settings":
        """Em produção, um driver de pagamento real exige PAYMENT_WEBHOOK_SECRET
        configurado — sem isso, o webhook aceitaria qualquer payload sem
        verificar a assinatura (ver
        `PaymentGateway.parse_webhook_event`/`ConsoleGateway.
        parse_webhook_event` em app/services/billing/gateway.py, ADR-016,
        que pula a checagem quando o segredo está vazio). O driver "console"
        fica isento porque não fala com nenhum provedor real e não há
        assinatura para validar.
        """
        if (
            self.APP_ENV == "production"
            and self.PAYMENT_GATEWAY_DRIVER != "console"
            and not self.PAYMENT_WEBHOOK_SECRET
        ):
            raise ValueError(
                "PAYMENT_WEBHOOK_SECRET é obrigatório em produção quando "
                f"PAYMENT_GATEWAY_DRIVER='{self.PAYMENT_GATEWAY_DRIVER}' (driver "
                "diferente de 'console'). Configure a variável de ambiente antes "
                "de subir este serviço."
            )
        return self

    # app/core/config.py (adicionar ao final da classe Settings)

    # --- Notificações transacionais (PROMPT 13) --------------------------- #
    # Flags de ativação por tipo de evento
    NOTIFY_PAYMENT_APPROVED: bool = Field(default=True)
    NOTIFY_PAYMENT_FAILED: bool = Field(default=True)
    NOTIFY_RENEWAL_SUCCESS: bool = Field(default=True)
    NOTIFY_RENEWAL_REMINDER: bool = Field(default=True)
    NOTIFY_CANCELLATION: bool = Field(default=True)
    NOTIFY_REACTIVATION: bool = Field(default=True)
    NOTIFY_PLAN_CHANGE: bool = Field(default=True)
    NOTIFY_DUNNING_RECOVERED: bool = Field(default=True)
    NOTIFY_DUNNING_RETRY_FAILED: bool = Field(default=True)
    NOTIFY_DUNNING_EXPIRED: bool = Field(default=True)

    # Dias de antecedência para aviso de renovação
    RENEWAL_REMINDER_DAYS_BEFORE: int = Field(default=3, ge=1, le=7)

    # Adicionar ao final da classe Settings

    # Scheduler / Workers
    SCHEDULER_ENABLED: bool = Field(
        default=True,
        description="Habilita o scheduler in-process. Desabilite em workers secundários.",
    )
    SCHEDULER_LOCK_TTL_SECONDS: int = Field(
        default=300,
        ge=30,
        description="TTL do lock distribuído para jobs em segundos.",
    )

        # Adicionar ao final da classe Settings

    # Cache
    CACHE_ENABLED: bool = Field(
        default=True,
        description="Habilita o cache distribuído via Redis.",
    )
    CACHE_DEFAULT_TTL_SECONDS: int = Field(
        default=3600,
        ge=60,
        description="TTL padrão para cache em segundos.",
    )
    CACHE_PLANS_TTL_SECONDS: int = Field(
        default=3600,
        ge=60,
        description="TTL para cache de planos em segundos.",
    )
    CACHE_USER_TTL_SECONDS: int = Field(
        default=300,
        ge=60,
        description="TTL para cache de usuários em segundos.",
    )

    


@lru_cache
def get_settings() -> Settings:
    """Settings em cache — lida do ambiente uma única vez por processo."""
    return Settings()


settings = get_settings()

