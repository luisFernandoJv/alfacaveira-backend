"""Métricas para observabilidade (Prometheus).

Utiliza a biblioteca prometheus_client para expor métricas
em um endpoint `/metrics` compatível com o Prometheus.
"""

import time
import asyncio
from functools import wraps
from typing import Any, Callable, Optional

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Classes dummy para evitar erros de importação
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def _child(self): return self
    
    class Gauge:
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
    
    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def observe(self, *args, **kwargs): pass
    
    class Info:
        def __init__(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass
    
    async def generate_latest(): return b""
    CONTENT_TYPE_LATEST = "text/plain"


# ============================================================================
# HTTP Métricas
# ============================================================================

if PROMETHEUS_AVAILABLE:
    http_requests_total = Counter(
        "http_requests_total",
        "Total de requisições HTTP",
        ["method", "path", "status_code"],
    )

    http_request_duration_seconds = Histogram(
        "http_request_duration_seconds",
        "Duração das requisições HTTP",
        ["method", "path"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
    )

    http_requests_in_flight = Gauge(
        "http_requests_in_flight",
        "Requisições HTTP em andamento",
        ["method"],
    )

    # ============================================================================
    # Billing Métricas
    # ============================================================================

    billing_events_total = Counter(
        "billing_events_total",
        "Total de eventos de billing",
        ["event_type", "status"],
    )

    billing_subscriptions_active = Gauge(
        "billing_subscriptions_active",
        "Número de assinaturas ativas",
    )

    billing_subscriptions_by_plan = Gauge(
        "billing_subscriptions_by_plan",
        "Número de assinaturas por plano",
        ["plan_slug"],
    )

    billing_revenue_total = Counter(
        "billing_revenue_total",
        "Receita total (em centavos)",
        ["plan_slug", "period"],
    )

    billing_payment_duration_seconds = Histogram(
        "billing_payment_duration_seconds",
        "Duração do processamento de pagamento",
        ["provider", "status"],
        buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
    )

    billing_webhook_events_total = Counter(
        "billing_webhook_events_total",
        "Total de eventos de webhook processados",
        ["provider", "event_type", "status"],
    )

    # ============================================================================
    # Auth Métricas
    # ============================================================================

    auth_events_total = Counter(
        "auth_events_total",
        "Total de eventos de autenticação",
        ["event_type", "status"],
    )

    auth_login_attempts_total = Counter(
        "auth_login_attempts_total",
        "Tentativas de login",
        ["status"],
    )

    auth_refresh_attempts_total = Counter(
        "auth_refresh_attempts_total",
        "Tentativas de refresh token",
        ["status"],
    )

    # ============================================================================
    # Métricas de Negócio
    # ============================================================================

    business_users_total = Gauge(
        "business_users_total",
        "Total de usuários",
        ["status"],
    )

    business_questions_total = Gauge(
        "business_questions_total",
        "Total de questões no banco",
        ["status"],
    )

    business_training_sessions_total = Counter(
        "business_training_sessions_total",
        "Total de sessões de treino criadas",
        ["status"],
    )

    # ============================================================================
    # Information
    # ============================================================================

    app_info = Info(
        "app_info",
        "Informações da aplicação",
    )

    def set_app_info(version: str = "0.1.0", env: str = "development") -> None:
        """Define informações da aplicação."""
        app_info.info({"version": version, "environment": env})

else:
    # Dummies
    class _Dummy:
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass

    http_requests_total = _Dummy()
    http_request_duration_seconds = _Dummy()
    http_requests_in_flight = _Dummy()
    billing_events_total = _Dummy()
    billing_subscriptions_active = _Dummy()
    billing_subscriptions_by_plan = _Dummy()
    billing_revenue_total = _Dummy()
    billing_payment_duration_seconds = _Dummy()
    billing_webhook_events_total = _Dummy()
    auth_events_total = _Dummy()
    auth_login_attempts_total = _Dummy()
    auth_refresh_attempts_total = _Dummy()
    business_users_total = _Dummy()
    business_questions_total = _Dummy()
    business_training_sessions_total = _Dummy()
    app_info = _Dummy()

    def set_app_info(version: str = "0.1.0", env: str = "development") -> None:
        pass


# ============================================================================
# Helpers
# ============================================================================

def track_http_request(method: str, path: str, status_code: int, duration: float) -> None:
    """Registra métricas de uma requisição HTTP."""
    if PROMETHEUS_AVAILABLE:
        http_requests_total.labels(method=method, path=path, status_code=str(status_code)).inc()
        http_request_duration_seconds.labels(method=method, path=path).observe(duration)


def track_billing_event(event_type: str, status: str) -> None:
    """Registra um evento de billing."""
    if PROMETHEUS_AVAILABLE:
        billing_events_total.labels(event_type=event_type, status=status).inc()


def track_webhook_event(provider: str, event_type: str, status: str) -> None:
    """Registra um evento de webhook."""
    if PROMETHEUS_AVAILABLE:
        billing_webhook_events_total.labels(
            provider=provider,
            event_type=event_type,
            status=status,
        ).inc()


def track_auth_event(event_type: str, status: str) -> None:
    """Registra um evento de autenticação."""
    if PROMETHEUS_AVAILABLE:
        auth_events_total.labels(event_type=event_type, status=status).inc()


def track_payment_duration(provider: str, status: str, duration: float) -> None:
    """Registra duração de processamento de pagamento."""
    if PROMETHEUS_AVAILABLE:
        billing_payment_duration_seconds.labels(provider=provider, status=status).observe(duration)


async def metrics_endpoint() -> tuple[bytes, int, dict[str, str]]:
    """Endpoint para expor métricas no formato Prometheus."""
    if PROMETHEUS_AVAILABLE:
        return (
            generate_latest(),
            200,
            {"Content-Type": CONTENT_TYPE_LATEST},
        )
    return b"", 404, {}


# ============================================================================
# Decorators
# ============================================================================

def timed(metric: Any = None, labels: dict[str, str] | None = None) -> Callable:
    """Decorator para medir tempo de execução de funções."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration = time.perf_counter() - start
                if PROMETHEUS_AVAILABLE and metric:
                    metric.labels(**(labels or {})).observe(duration)
                return result
            except Exception:
                duration = time.perf_counter() - start
                if PROMETHEUS_AVAILABLE and metric:
                    metric.labels(**(labels or {})).observe(duration)
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration = time.perf_counter() - start
                if PROMETHEUS_AVAILABLE and metric:
                    metric.labels(**(labels or {})).observe(duration)
                return result
            except Exception:
                duration = time.perf_counter() - start
                if PROMETHEUS_AVAILABLE and metric:
                    metric.labels(**(labels or {})).observe(duration)
                raise

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def count_event(metric: Any, labels: dict[str, str] | None = None) -> Callable:
    """Decorator para contar eventos."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            try:
                result = await func(*args, **kwargs)
                if PROMETHEUS_AVAILABLE and metric:
                    metric.labels(**(labels or {})).inc()
                return result
            except Exception:
                if PROMETHEUS_AVAILABLE and metric:
                    metric.labels(**(labels or {}), status="error").inc()
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            try:
                result = func(*args, **kwargs)
                if PROMETHEUS_AVAILABLE and metric:
                    metric.labels(**(labels or {})).inc()
                return result
            except Exception:
                if PROMETHEUS_AVAILABLE and metric:
                    metric.labels(**(labels or {}), status="error").inc()
                raise

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator