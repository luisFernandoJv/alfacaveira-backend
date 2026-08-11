"""Application entrypoint: cria e configura a instância FastAPI."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.scheduler import shutdown_scheduler, start_scheduler
from app.middlewares.rate_limit import RateLimitMiddleware

logger = structlog.get_logger(__name__)

# Observabilidade (PROMPT 17)
try:
    from app.observability import ObservabilityMiddleware, metrics_endpoint, set_app_info
    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False
    async def metrics_endpoint():
        return b"", 404, {}
    def set_app_info(*args, **kwargs):
        pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    
    # Conecta ao Redis
    try:
        app.state.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await app.state.redis.ping()
        logger.info("redis.connected", url=settings.REDIS_URL)
    except Exception as e:
        logger.warning("redis.connection_failed", error=str(e))
        app.state.redis = None
    
    # Observabilidade
    if OBSERVABILITY_AVAILABLE:
        set_app_info(version="0.1.0", env=settings.APP_ENV)
    
    # Scheduler com lock distribuído (PROMPT 18)
    start_scheduler()
    
    yield
    
    # Shutdown
    shutdown_scheduler()
    if app.state.redis:
        await app.state.redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # Middlewares
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    
    if OBSERVABILITY_AVAILABLE:
        app.add_middleware(ObservabilityMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    if OBSERVABILITY_AVAILABLE:
        @app.get("/metrics", tags=["observability"])
        async def metrics() -> Response:
            body, status, headers = await metrics_endpoint()
            return Response(content=body, status_code=status, headers=headers)

    return app


app = create_app()