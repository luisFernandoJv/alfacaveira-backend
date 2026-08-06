"""Rate limiting simples baseado em Redis (INCR + EXPIRE por IP)."""

import time

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.responses import error_envelope


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Lê o cliente Redis de `request.app.state.redis` (definido no lifespan),
    em vez de recebê-lo no construtor — o middleware é montado antes do
    lifespan rodar, então o client ainda não existiria nesse momento."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):  # type: ignore[no-untyped-def]
        try:
            # Verifica se o cliente Redis existe no estado da aplicação
            redis_client = getattr(request.app.state, "redis", None)
            if redis_client:
                client_ip = request.client.host if request.client else "unknown"
                window = int(time.time() // 60)
                key = f"ratelimit:{client_ip}:{window}"

                current = await redis_client.incr(key)
                if current == 1:
                    await redis_client.expire(key, 60)

                if current > settings.RATE_LIMIT_PER_MINUTE:
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content=error_envelope("rate_limited", "Muitas requisições. Tente novamente em instantes."),
                    )
        except Exception:
            # Fallback seguro: se o Redis estiver offline ou indisponível,
            # a requisição prossegue normalmente sem derrubar a API com erro 500.
            pass

        return await call_next(request)