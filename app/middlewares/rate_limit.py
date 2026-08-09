"""Rate limiting baseado em Redis (INCR + EXPIRE por IP), com políticas
dedicadas por rota e comportamento explícito quando o Redis está
indisponível.

Antes desta versão, toda a API compartilhava um único balde
(`RATE_LIMIT_PER_MINUTE`, 60 req/min por IP) — o que deixava login/registro
(alvo de força bruta) e forgot-password (alvo de enumeração/flood de
e-mail) tão permissivos quanto rotas de leitura pública, e uma falha do
Redis era engolida em silêncio (`except Exception: pass`), sem log e sem
decisão declarada sobre o que deveria acontecer nesse caso.

Este módulo resolve, por requisição, qual política se aplica com base no
prefixo da rota (`_resolve_policy`) e aplica o mesmo algoritmo de janela
fixa por IP já usado antes, mas com um contador isolado por política
(`ratelimit:{policy}:{ip}:{window}`), então esgotar o limite de login não
consome o limite de outra rota nem vice-versa.
"""

import time
from dataclasses import dataclass

import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import settings
from app.core.responses import error_envelope

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    limit_per_minute: int


def _resolve_policy(path: str) -> RateLimitPolicy:
    """Mapeia o caminho da requisição para a política dedicada mais
    específica, ou para a política `default` se nenhuma casar.

    Lê `settings` a cada chamada (não em import-time) de propósito: os
    valores continuam configuráveis via variável de ambiente/override em
    teste sem exigir recarregar o módulo.
    """
    prefix = settings.API_V1_PREFIX
    route_policies: tuple[tuple[str, str, int], ...] = (
        (f"{prefix}/auth/login", "login", settings.RATE_LIMIT_LOGIN_PER_MINUTE),
        (f"{prefix}/auth/register", "register", settings.RATE_LIMIT_REGISTER_PER_MINUTE),
        (
            f"{prefix}/auth/forgot-password",
            "forgot_password",
            settings.RATE_LIMIT_FORGOT_PASSWORD_PER_MINUTE,
        ),
        (
            f"{prefix}/auth/reset-password",
            "reset_password",
            settings.RATE_LIMIT_RESET_PASSWORD_PER_MINUTE,
        ),
        (f"{prefix}/billing", "billing", settings.RATE_LIMIT_BILLING_PER_MINUTE),
    )

    for route_prefix, name, limit in route_policies:
        if path.startswith(route_prefix):
            return RateLimitPolicy(name=name, limit_per_minute=limit)

    return RateLimitPolicy(name="default", limit_per_minute=settings.RATE_LIMIT_PER_MINUTE)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Lê o cliente Redis de `request.app.state.redis` (definido no
    lifespan), em vez de recebê-lo no construtor — o middleware é montado
    antes do lifespan rodar, então o client ainda não existiria nesse
    momento.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):  # type: ignore[no-untyped-def]
        policy = _resolve_policy(request.url.path)
        redis_client = getattr(request.app.state, "redis", None)

        if redis_client is None:
            return await self._on_backend_unavailable(
                request, call_next, policy, reason="redis_client_not_configured"
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            window = int(time.time() // 60)
            key = f"ratelimit:{policy.name}:{client_ip}:{window}"

            current = await redis_client.incr(key)
            if current == 1:
                await redis_client.expire(key, 60)

            if current > policy.limit_per_minute:
                logger.warning(
                    "rate_limit.exceeded",
                    policy=policy.name,
                    path=request.url.path,
                    client_ip=client_ip,
                    limit=policy.limit_per_minute,
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content=error_envelope(
                        "rate_limited", "Muitas requisições. Tente novamente em instantes."
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - Redis pode falhar de várias formas
            return await self._on_backend_unavailable(
                request, call_next, policy, reason=repr(exc)
            )

        return await call_next(request)

    async def _on_backend_unavailable(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
        policy: RateLimitPolicy,
        reason: str,
    ):  # type: ignore[no-untyped-def]
        """Comportamento explícito e observável quando o Redis está
        indisponível — controlado por `settings.RATE_LIMIT_FAIL_OPEN`. Ver
        docstring do campo em `app/core/config.py` para a decisão de
        negócio por trás do default.
        """
        logger.warning(
            "rate_limit.backend_unavailable",
            policy=policy.name,
            path=request.url.path,
            reason=reason,
            fail_open=settings.RATE_LIMIT_FAIL_OPEN,
        )

        if settings.RATE_LIMIT_FAIL_OPEN:
            return await call_next(request)

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_envelope(
                "rate_limit_unavailable",
                "Serviço de proteção contra abuso indisponível. Tente novamente em instantes.",
            ),
        )