"""Agendador in-process do worker `app.workers.analytics_aggregator`.

Contexto (ver docstring de `analytics_aggregator.py`): o projeto não tem
fila/agendador dedicado (`docs/architecture.md` só lista Redis para rate
limit — nada de Celery/APScheduler). A API hoje roda como um **processo
único** de uvicorn (sem `--workers`, ver `Dockerfile`/`docker-compose.yml`),
então o caminho mais simples — sem introduzir infraestrutura nova — é
agendar o worker dentro do próprio processo, via APScheduler, iniciado e
parado junto do `lifespan` de `app/main.py`.

Dois jobs, replicando a recomendação já deixada na docstring do worker:

- `analytics_aggregator_frequent`: a cada
  `ANALYTICS_AGGREGATOR_INTERVAL_MINUTES` minutos, `--days 2` (hoje + ontem,
  cobre fuso horário e execuções atrasadas) — mantém `user_daily_stats` e o
  streak quase em tempo real.
- `analytics_aggregator_daily`: 1x/dia, às
  `ANALYTICS_AGGREGATOR_DAILY_HOUR_UTC`h UTC, com janela maior
  (`ANALYTICS_AGGREGATOR_DAILY_WINDOW_DAYS`) para reconciliar eventuais
  falhas de execuções anteriores.

`user_subject_stats` e `study_streaks` são sempre recalculados por completo
dentro de cada chamada de `run()` (ver worker), então os dois jobs também os
mantêm em dia — o parâmetro `days` só afeta a janela de `user_daily_stats`.

ATENÇÃO — escala horizontal: isso só é seguro enquanto a API rodar como uma
única instância/processo. Se o deploy futuramente escalar para múltiplas
instâncias (ou `--workers` > 1 no uvicorn), estes jobs vão disparar em
duplicidade — inofensivo em termos de dado (o worker é idempotente via
upsert), mas desperdiça trabalho e conexões de banco. Nesse cenário, mover
para um cron externo único (ou lock distribuído via Redis, que o projeto já
usa para rate limit) em vez de manter o agendamento in-process.
"""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.workers.analytics_aggregator import run as run_analytics_aggregator

logger = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

_FREQUENT_JOB_ID = "analytics_aggregator_frequent"
_DAILY_JOB_ID = "analytics_aggregator_daily"


async def _run_aggregator_job(days: int, job_name: str) -> None:
    """Roda o worker e loga início/fim/falha — nunca deixa a exceção silenciosa."""
    logger.info("analytics_aggregator.job_start", job=job_name, days=days)
    try:
        await run_analytics_aggregator(days=days)
    except Exception:
        # Não relança para o scheduler: uma falha não deve remover o job do
        # schedule (a próxima execução tenta de novo). Fica logado como
        # exception para aparecer em qualquer monitoramento de logs.
        logger.exception("analytics_aggregator.job_failed", job=job_name)
    else:
        logger.info("analytics_aggregator.job_finished", job=job_name)


def start_scheduler() -> None:
    """Registra os jobs e inicia o scheduler. Chamar uma vez, no lifespan do FastAPI."""
    if not settings.ANALYTICS_AGGREGATOR_ENABLED:
        logger.info("analytics_aggregator.scheduler_disabled")
        return

    scheduler.add_job(
        _run_aggregator_job,
        trigger=IntervalTrigger(minutes=settings.ANALYTICS_AGGREGATOR_INTERVAL_MINUTES),
        kwargs={"days": 2, "job_name": "frequent"},
        id=_FREQUENT_JOB_ID,
        replace_existing=True,
        coalesce=True,  # se o processo ficar sem CPU e perder execuções, roda só 1x ao voltar
        max_instances=1,  # nunca duas execuções sobrepostas do mesmo job
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_aggregator_job,
        trigger=CronTrigger(hour=settings.ANALYTICS_AGGREGATOR_DAILY_HOUR_UTC, minute=0),
        kwargs={
            "days": settings.ANALYTICS_AGGREGATOR_DAILY_WINDOW_DAYS,
            "job_name": "daily_reconciliation",
        },
        id=_DAILY_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        "analytics_aggregator.scheduler_started",
        interval_minutes=settings.ANALYTICS_AGGREGATOR_INTERVAL_MINUTES,
        daily_hour_utc=settings.ANALYTICS_AGGREGATOR_DAILY_HOUR_UTC,
        daily_window_days=settings.ANALYTICS_AGGREGATOR_DAILY_WINDOW_DAYS,
    )


def shutdown_scheduler() -> None:
    """Para o scheduler. Chamar no shutdown do lifespan, antes de fechar o Redis."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("analytics_aggregator.scheduler_stopped")