"""Agendador in-process com lock distribuído para multi-instância."""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.workers.analytics_aggregator import run as run_analytics_aggregator
from app.workers.subscription_dunning import run as run_subscription_dunning
from app.workers.subscription_renewal import run as run_subscription_renewal
from app.workers.ranking_updater import update_rankings

logger = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

_FREQUENT_JOB_ID = "analytics_aggregator_frequent"
_DAILY_JOB_ID = "analytics_aggregator_daily"
_SUBSCRIPTION_RENEWAL_JOB_ID = "subscription_renewal"
_SUBSCRIPTION_DUNNING_JOB_ID = "subscription_dunning"


async def _get_redis_client():
    """Obtém o cliente Redis do app state."""
    from app.main import app
    return getattr(app.state, "redis", None)


async def _run_with_lock(
    job_func,
    job_name: str,
    lock_ttl: int = 300,
    *args,
    **kwargs,
):
    """Executa um job com lock distribuído."""
    redis_client = await _get_redis_client()

    if redis_client is None:
        logger.warning(
            "job.redis_unavailable",
            job=job_name,
            fallback="executing without lock",
        )
        await job_func(*args, **kwargs)
        return

    from app.core.lock import create_lock

    lock = create_lock(redis_client, job_name, ttl=lock_ttl)

    logger.info(
        "job.acquiring_lock",
        job=job_name,
        lock_key=lock.lock_key,
    )

    async with lock as acquired:
        if not acquired:
            logger.info(
                "job.skipped",
                job=job_name,
                reason="lock_acquired_by_another_instance",
            )
            return

        logger.info(
            "job.starting",
            job=job_name,
        )
        try:
            await job_func(*args, **kwargs)
        except Exception as e:
            logger.exception(
                "job.failed",
                job=job_name,
                error=str(e),
            )
            raise
        else:
            logger.info(
                "job.completed",
                job=job_name,
            )


async def _run_aggregator_job(days: int, job_name: str) -> None:
    await _run_with_lock(
        run_analytics_aggregator,
        job_name=job_name,
        lock_ttl=600,
        days=days,
    )


async def _run_subscription_renewal_job() -> None:
    await _run_with_lock(
        run_subscription_renewal,
        job_name="subscription_renewal",
        lock_ttl=300,
    )


async def _run_subscription_dunning_job() -> None:
    await _run_with_lock(
        run_subscription_dunning,
        job_name="subscription_dunning",
        lock_ttl=300,
    )


def start_scheduler() -> None:
    """Registra os jobs e inicia o scheduler."""
    if not settings.SCHEDULER_ENABLED:
        logger.info("scheduler.disabled", reason="SCHEDULER_ENABLED=false")
        return

    if settings.ANALYTICS_AGGREGATOR_ENABLED:
        _register_analytics_jobs()
    else:
        logger.info("analytics_aggregator.scheduler_disabled")

    if settings.SUBSCRIPTION_RENEWAL_ENABLED:
        scheduler.add_job(
            _run_subscription_renewal_job,
            trigger=IntervalTrigger(minutes=settings.SUBSCRIPTION_RENEWAL_INTERVAL_MINUTES),
            id=_SUBSCRIPTION_RENEWAL_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=600,
        )

        scheduler.add_job(
            update_rankings,
            trigger=IntervalTrigger(minutes=30),
            id="ranking_updater",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
        )
        logger.info(
            "subscription_renewal.scheduler_job_registered",
            interval_minutes=settings.SUBSCRIPTION_RENEWAL_INTERVAL_MINUTES,
        )
    else:
        logger.info("subscription_renewal.scheduler_disabled")

    if settings.DUNNING_ENABLED:
        scheduler.add_job(
            _run_subscription_dunning_job,
            trigger=IntervalTrigger(minutes=settings.DUNNING_INTERVAL_MINUTES),
            id=_SUBSCRIPTION_DUNNING_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=600,
        )
        logger.info(
            "subscription_dunning.scheduler_job_registered",
            interval_minutes=settings.DUNNING_INTERVAL_MINUTES,
        )
    else:
        logger.info("subscription_dunning.scheduler_disabled")

    if scheduler.get_jobs():
        scheduler.start()
        logger.info("scheduler.started")


def _register_analytics_jobs() -> None:
    scheduler.add_job(
        _run_aggregator_job,
        trigger=IntervalTrigger(minutes=settings.ANALYTICS_AGGREGATOR_INTERVAL_MINUTES),
        kwargs={"days": 2, "job_name": "analytics_aggregator_frequent"},
        id=_FREQUENT_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_aggregator_job,
        trigger=CronTrigger(hour=settings.ANALYTICS_AGGREGATOR_DAILY_HOUR_UTC, minute=0),
        kwargs={
            "days": settings.ANALYTICS_AGGREGATOR_DAILY_WINDOW_DAYS,
            "job_name": "analytics_aggregator_daily",
        },
        id=_DAILY_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info(
        "analytics_aggregator.jobs_registered",
        interval_minutes=settings.ANALYTICS_AGGREGATOR_INTERVAL_MINUTES,
        daily_hour_utc=settings.ANALYTICS_AGGREGATOR_DAILY_HOUR_UTC,
        daily_window_days=settings.ANALYTICS_AGGREGATOR_DAILY_WINDOW_DAYS,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler.stopped")