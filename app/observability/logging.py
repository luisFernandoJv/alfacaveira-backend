"""Logger estruturado com contexto por requisição.

Utiliza structlog para logs estruturados com campos padronizados.
Adiciona contexto automático para cada requisição (request_id, user_id, etc.).
"""

import structlog
from structlog.contextvars import bind_contextvars, unbind_contextvars, clear_contextvars
from contextlib import contextmanager
from typing import Any, Dict, Optional
import uuid

from app.core.config import settings

# ============================================================================
# Configuração do Logger
# ============================================================================

def configure_logging() -> None:
    """Configura o structlog com os processadores padrão."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
            if settings.APP_ENV == "production"
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ============================================================================
# Logger com Contexto
# ============================================================================

class ContextLogger:
    """Logger com contexto por requisição."""

    def __init__(self, name: str = "app"):
        self._logger = structlog.get_logger(name)
        self._context: Dict[str, Any] = {}

    def bind(self, **kwargs) -> "ContextLogger":
        """Adiciona contexto ao logger."""
        self._context.update(kwargs)
        return self

    def unbind(self, *keys) -> "ContextLogger":
        """Remove contexto do logger."""
        for key in keys:
            self._context.pop(key, None)
        return self

    def clear(self) -> "ContextLogger":
        """Limpa todo o contexto."""
        self._context.clear()
        return self

    def _log(self, level: str, msg: str, **kwargs) -> None:
        """Loga uma mensagem com o nível especificado."""
        all_kwargs = {**self._context, **kwargs}
        getattr(self._logger, level)(msg, **all_kwargs)

    def debug(self, msg: str, **kwargs) -> None:
        self._log("debug", msg, **kwargs)

    def info(self, msg: str, **kwargs) -> None:
        self._log("info", msg, **kwargs)

    def warning(self, msg: str, **kwargs) -> None:
        self._log("warning", msg, **kwargs)

    def error(self, msg: str, **kwargs) -> None:
        self._log("error", msg, **kwargs)

    def critical(self, msg: str, **kwargs) -> None:
        self._log("critical", msg, **kwargs)

    def exception(self, msg: str, **kwargs) -> None:
        self._log("error", msg, exc_info=True, **kwargs)


# ============================================================================
# Helpers de Contexto
# ============================================================================

def get_logger(name: str = "app") -> ContextLogger:
    """Retorna um logger com contexto."""
    return ContextLogger(name)


@contextmanager
def request_context(
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs,
):
    """Contexto de requisição para logs estruturados."""
    request_id = request_id or str(uuid.uuid4())
    bind_contextvars(request_id=request_id, user_id=user_id, **kwargs)
    try:
        yield request_id
    finally:
        clear_contextvars()


# ============================================================================
# Logs de Eventos de Negócio
# ============================================================================

def log_billing_event(
    event_type: str,
    status: str,
    user_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
    payment_id: Optional[str] = None,
    **kwargs,
) -> None:
    """Loga um evento de billing."""
    logger = get_logger("billing")
    logger.info(
        f"billing.{event_type}",
        event_type=event_type,
        status=status,
        user_id=user_id,
        subscription_id=subscription_id,
        payment_id=payment_id,
        **kwargs,
    )


def log_auth_event(
    event_type: str,
    status: str,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    **kwargs,
) -> None:
    """Loga um evento de autenticação."""
    logger = get_logger("auth")
    logger.info(
        f"auth.{event_type}",
        event_type=event_type,
        status=status,
        user_id=user_id,
        email=email,
        **kwargs,
    )


def log_webhook_event(
    provider: str,
    event_type: str,
    status: str,
    payload: Optional[Dict] = None,
    **kwargs,
) -> None:
    """Loga um evento de webhook."""
    logger = get_logger("webhook")
    logger.info(
        f"webhook.{provider}.{event_type}",
        provider=provider,
        event_type=event_type,
        status=status,
        **kwargs,
    )


def log_payment_event(
    event_type: str,
    status: str,
    amount_cents: int,
    user_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
    payment_id: Optional[str] = None,
    provider: Optional[str] = None,
    **kwargs,
) -> None:
    """Loga um evento de pagamento."""
    logger = get_logger("payment")
    logger.info(
        f"payment.{event_type}",
        event_type=event_type,
        status=status,
        amount_cents=amount_cents,
        user_id=user_id,
        subscription_id=subscription_id,
        payment_id=payment_id,
        provider=provider,
        **kwargs,
    )