"""Middleware para observabilidade: logs, métricas e tracing."""

import time
from typing import Any, Callable, Awaitable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import uuid

from app.observability.logging import request_context, get_logger
from app.core.config import settings

try:
    from app.observability.metrics import track_http_request, http_requests_in_flight
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    def track_http_request(*args, **kwargs): pass
    class _DummyGauge:
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass
    http_requests_in_flight = _DummyGauge()


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware para observabilidade: logs, métricas e tracing."""

    EXCLUDED_PATHS = [
        "/health",
        "/metrics",
        "/favicon.ico",
        "/robots.txt",
        "/static",
        "/_next",
    ]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Gera request_id
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Verifica se o path deve ser excluído
        path = request.url.path
        if any(path.startswith(excl) for excl in self.EXCLUDED_PATHS):
            return await call_next(request)

        # Contexto para logs
        user_id = getattr(request.state, "user_id", None)
        with request_context(
            request_id=request_id,
            user_id=user_id,
            method=request.method,
            path=path,
            client_ip=request.client.host if request.client else None,
        ):
            logger = get_logger("http")

            # Métricas: requisições em andamento
            if METRICS_AVAILABLE:
                http_requests_in_flight.labels(method=request.method).inc()

            start = time.perf_counter()

            try:
                response = await call_next(request)
                duration = time.perf_counter() - start

                # Métricas
                if METRICS_AVAILABLE:
                    track_http_request(request.method, path, response.status_code, duration)

                # Log da requisição
                logger.info(
                    "http.request",
                    method=request.method,
                    path=path,
                    status_code=response.status_code,
                    duration_ms=round(duration * 1000, 2),
                    content_length=response.headers.get("content-length"),
                )

                return response

            except Exception as exc:
                duration = time.perf_counter() - start

                # Métricas
                if METRICS_AVAILABLE:
                    track_http_request(request.method, path, 500, duration)

                # Log do erro
                logger.exception(
                    "http.request.error",
                    method=request.method,
                    path=path,
                    duration_ms=round(duration * 1000, 2),
                    error=str(exc),
                )

                raise

            finally:
                if METRICS_AVAILABLE:
                    http_requests_in_flight.labels(method=request.method).dec()