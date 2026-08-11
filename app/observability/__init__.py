"""Módulo de observabilidade: logs, métricas e monitoramento."""

from app.observability.logging import (
    ContextLogger,
    get_logger,
    request_context,
    log_billing_event,
    log_auth_event,
    log_webhook_event,
    log_payment_event,
    configure_logging,
)

# Importações seguras para métricas
try:
    from app.observability.metrics import (
        # HTTP
        http_requests_total,
        http_request_duration_seconds,
        http_requests_in_flight,
        # Billing
        billing_events_total,
        billing_subscriptions_active,
        billing_subscriptions_by_plan,
        billing_revenue_total,
        billing_payment_duration_seconds,
        billing_webhook_events_total,
        # Auth
        auth_events_total,
        auth_login_attempts_total,
        auth_refresh_attempts_total,
        # Business
        business_users_total,
        business_questions_total,
        business_training_sessions_total,
        # Helpers
        track_http_request,
        track_billing_event,
        track_webhook_event,
        track_auth_event,
        track_payment_duration,
        set_app_info,
        metrics_endpoint,
        timed,
        count_event,
    )
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    # Fallbacks
    def track_http_request(*args, **kwargs): pass
    def track_billing_event(*args, **kwargs): pass
    def track_webhook_event(*args, **kwargs): pass
    def track_auth_event(*args, **kwargs): pass
    def track_payment_duration(*args, **kwargs): pass
    def set_app_info(*args, **kwargs): pass
    async def metrics_endpoint(): return b"", 404, {}


from app.observability.middleware import ObservabilityMiddleware

__all__ = [
    # Logging
    "ContextLogger",
    "get_logger",
    "request_context",
    "log_billing_event",
    "log_auth_event",
    "log_webhook_event",
    "log_payment_event",
    "configure_logging",
    # Metrics
    "http_requests_total",
    "http_request_duration_seconds",
    "http_requests_in_flight",
    "billing_events_total",
    "billing_subscriptions_active",
    "billing_subscriptions_by_plan",
    "billing_revenue_total",
    "billing_payment_duration_seconds",
    "billing_webhook_events_total",
    "auth_events_total",
    "auth_login_attempts_total",
    "auth_refresh_attempts_total",
    "business_users_total",
    "business_questions_total",
    "business_training_sessions_total",
    "track_http_request",
    "track_billing_event",
    "track_webhook_event",
    "track_auth_event",
    "track_payment_duration",
    "set_app_info",
    "metrics_endpoint",
    "timed",
    "count_event",
    # Middleware
    "ObservabilityMiddleware",
    # Status
    "METRICS_AVAILABLE",
    "OBSERVABILITY_AVAILABLE",
]