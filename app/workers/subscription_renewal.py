"""Worker de renovação automática de assinaturas (PROMPT 10, roadmap item 10).

Com cache de usuários para otimização (PROMPT 19).
"""

import argparse
import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.core.config import settings
from app.database.session import AsyncSessionFactory
from app.models.enums import PaymentStatus
from app.models.enums import SubscriptionStatus
from app.repositories.billing.subscription_repository import SubscriptionRepository
from app.repositories.identity.user_repository import UserRepository
from app.services.billing.payment_service import PaymentService
from app.services.billing.subscription_service import SubscriptionService
from app.services.billing.notification_service import SubscriptionNotificationService
from app.services.platform.notification_service import NotificationService

logger = structlog.get_logger(__name__)

# Cache de usuários (TTL: 5 minutos)
USER_CACHE_TTL = 300


async def _get_user_with_cache(user_repo: UserRepository, user_id):
    """Busca usuário com cache."""
    cache = get_cache()
    cache_key = f"user:{user_id}"

    if cache:
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.debug("user.cache_hit", user_id=str(user_id))
            return cached

    user = await user_repo.get_by_id(user_id)

    if cache and user:
        await cache.set(cache_key, user, ttl=USER_CACHE_TTL)

    return user


async def _charge_and_apply(
    payment_service: PaymentService,
    subscription_service: SubscriptionService,
    subscription_id,
) -> None:
    """Tentativa única de cobrança de renovação para uma assinatura."""
    payment = await payment_service.charge_subscription(subscription_id)
    if payment.status == PaymentStatus.APROVADO:
        await subscription_service.renew_subscription_system(subscription_id, payment_id=payment.id)
    elif payment.status in (PaymentStatus.RECUSADO, PaymentStatus.ESTORNADO):
        await subscription_service.mark_payment_failed(subscription_id)


async def run_once(session: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Uma execução do job."""
    now = now or datetime.now(UTC)
    subscriptions = SubscriptionRepository(session)
    payment_service = PaymentService(session)
    subscription_service = SubscriptionService(session)
    notification_service = SubscriptionNotificationService(
        notification_service=NotificationService(session)
    )
    user_repo = UserRepository(session)

    reminders_sent = 0

    # ================================================================== #
    # 1. Lembrete de renovação (PROMPT 13)                               #
    # ================================================================== #
    if settings.NOTIFY_RENEWAL_REMINDER:
        due_for_reminder = await subscriptions.list_due_for_renewal_reminder(
            now, settings.RENEWAL_REMINDER_DAYS_BEFORE
        )
        for subscription in due_for_reminder:
            logger.info(
                "subscription_renewal.sending_reminder",
                subscription_id=str(subscription.id),
                user_id=str(subscription.user_id),
                days_before=settings.RENEWAL_REMINDER_DAYS_BEFORE,
            )
            try:
                # Usa cache para buscar usuário
                user = await _get_user_with_cache(user_repo, subscription.user_id)
                if user:
                    await notification_service.notify_renewal_reminder(user, subscription)
                    await subscriptions.mark_renewal_reminder_sent(subscription.id, now)
                    reminders_sent += 1
            except Exception:
                logger.exception(
                    "subscription_renewal.reminder_failed",
                    subscription_id=str(subscription.id),
                    user_id=str(subscription.user_id),
                )

    # ================================================================== #
    # 2. Aplicar downgrades agendados (PROMPT 12)                        #
    # ================================================================== #
    downgrades_applied = 0
    due = await subscriptions.list_due_for_renewal(now)

    for subscription in due:
        if subscription.pending_plan_id is not None:
            logger.info(
                "subscription_renewal.applying_downgrade",
                subscription_id=str(subscription.id),
                pending_plan_id=str(subscription.pending_plan_id),
                effective_at=subscription.pending_plan_effective_at,
            )
            try:
                await subscription_service.apply_pending_downgrade(subscription.id)
                downgrades_applied += 1
            except Exception:
                logger.exception(
                    "subscription_renewal.downgrade_failed",
                    subscription_id=str(subscription.id),
                )

    # ================================================================== #
    # 3. Cobrança de renovação                                            #
    # ================================================================== #
    due = await subscriptions.list_due_for_renewal(now)
    charged = 0

    for subscription in due:
        logger.info("subscription_renewal.charging", subscription_id=str(subscription.id))
        try:
            await _charge_and_apply(payment_service, subscription_service, subscription.id)
        except Exception:
            logger.exception(
                "subscription_renewal.charge_failed", subscription_id=str(subscription.id)
            )
            continue
        charged += 1

    # ================================================================== #
    # 4. Cancelamentos agendados vencidos                                 #
    # ================================================================== #
    scheduled_cancellations = await subscriptions.list_scheduled_cancellations_due(now)
    finalized = 0

    for subscription in scheduled_cancellations:
        logger.info(
            "subscription_renewal.finalizing_cancellation", subscription_id=str(subscription.id)
        )
        try:
            await subscription_service.finalize_scheduled_cancellation(subscription.id)
        except Exception:
            logger.exception(
                "subscription_renewal.finalize_cancellation_failed",
                subscription_id=str(subscription.id),
            )
            continue
        finalized += 1

    return {
        "reminders_sent": reminders_sent,
        "downgrades_applied": downgrades_applied,
        "charged": charged,
        "finalized_cancellations": finalized,
    }


async def run() -> None:
    """Ponto de entrada do worker."""
    async with AsyncSessionFactory() as session:
        result = await run_once(session)

    print(
        "Renovação automática concluída "
        f"(lembretes enviados: {result['reminders_sent']}, "
        f"downgrades aplicados: {result['downgrades_applied']}, "
        f"cobradas: {result['charged']}, cancelamentos efetivados: "
        f"{result['finalized_cancellations']})."
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Envia lembretes de renovação, aplica downgrades agendados, "
            "cobra assinaturas ATIVA vencidas e efetiva cancelamentos "
            "agendados vencidos."
        )
    )
    return parser.parse_args()


if __name__ == "__main__":
    _parse_args()
    asyncio.run(run())