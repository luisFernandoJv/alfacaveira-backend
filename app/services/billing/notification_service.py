"""Serviço de notificações transacionais de assinatura (PROMPT 13)."""

import math
import uuid
from datetime import datetime
from typing import Optional

import structlog

from app.core.config import settings
from app.models.billing.subscription import Subscription
from app.models.enums import SubscriptionEmailEvent
from app.models.identity.user import User
from app.services.identity.email_service import EmailService

logger = structlog.get_logger(__name__)


class SubscriptionNotificationService:
    """Serviço para notificações transacionais de assinatura."""

    # Mapeamento evento -> flag de configuração
    _FLAG_MAP = {
        SubscriptionEmailEvent.PAYMENT_APPROVED: "NOTIFY_PAYMENT_APPROVED",
        SubscriptionEmailEvent.PAYMENT_FAILED: "NOTIFY_PAYMENT_FAILED",
        SubscriptionEmailEvent.RENEWAL_SUCCESS: "NOTIFY_RENEWAL_SUCCESS",
        SubscriptionEmailEvent.RENEWAL_REMINDER: "NOTIFY_RENEWAL_REMINDER",
        SubscriptionEmailEvent.CANCELLATION: "NOTIFY_CANCELLATION",
        SubscriptionEmailEvent.REACTIVATION: "NOTIFY_REACTIVATION",
        SubscriptionEmailEvent.PLAN_CHANGE: "NOTIFY_PLAN_CHANGE",
        SubscriptionEmailEvent.DUNNING_RECOVERED: "NOTIFY_DUNNING_RECOVERED",
        SubscriptionEmailEvent.DUNNING_RETRY_FAILED: "NOTIFY_DUNNING_RETRY_FAILED",
        SubscriptionEmailEvent.DUNNING_EXPIRED: "NOTIFY_DUNNING_EXPIRED",
    }

    # Mapeamento evento -> subject do e-mail
    _SUBJECT_MAP = {
        SubscriptionEmailEvent.PAYMENT_APPROVED: "Pagamento aprovado — Alfa Caveira",
        SubscriptionEmailEvent.PAYMENT_FAILED: "Falha no pagamento — Alfa Caveira",
        SubscriptionEmailEvent.RENEWAL_SUCCESS: "Renovação realizada — Alfa Caveira",
        SubscriptionEmailEvent.RENEWAL_REMINDER: "Renovação em breve — Alfa Caveira",
        SubscriptionEmailEvent.CANCELLATION: "Plano cancelado — Alfa Caveira",
        SubscriptionEmailEvent.REACTIVATION: "Plano reativado — Alfa Caveira",
        SubscriptionEmailEvent.PLAN_CHANGE: "Plano alterado — Alfa Caveira",
        SubscriptionEmailEvent.DUNNING_RECOVERED: "Pagamento regularizado — Alfa Caveira",
        SubscriptionEmailEvent.DUNNING_RETRY_FAILED: "Pagamento falhou novamente — Alfa Caveira",
        SubscriptionEmailEvent.DUNNING_EXPIRED: "Plano expirado — Alfa Caveira",
    }

    def __init__(self, email_service: Optional[EmailService] = None):
        self._email_service = email_service or EmailService()

    def _should_send(self, event: SubscriptionEmailEvent) -> bool:
        """Verifica se a notificação está habilitada via configuração."""
        flag_name = self._FLAG_MAP.get(event)
        if flag_name is None:
            return False
        return getattr(settings, flag_name, True)

    def _get_subject(self, event: SubscriptionEmailEvent) -> str:
        """Retorna o subject para o evento."""
        return self._SUBJECT_MAP.get(event, "Atualização — Alfa Caveira")

    def _get_first_name(self, user: User) -> str:
        """Extrai o primeiro nome do usuário."""
        return user.full_name.split(" ")[0] if user.full_name else ""

    def _build_context(
        self,
        event: SubscriptionEmailEvent,
        subscription: Subscription,
        user: User,
        **extra,
    ) -> dict:
        """Constrói o contexto para o template, incluindo first_name."""
        context = {
            "first_name": self._get_first_name(user),
            "plan_name": subscription.plan.name,
            "amount": subscription.plan.price_cents / 100,
        }
        context.update(extra)
        return context

    async def _send(
        self,
        user: User,
        subscription: Subscription,
        event: SubscriptionEmailEvent,
        extra_context: Optional[dict] = None,
    ) -> None:
        """Método interno para enviar o e-mail."""
        if not self._should_send(event):
            return

        context = self._build_context(
            event, subscription, user, **(extra_context or {})
        )
        subject = self._get_subject(event)

        try:
            await self._email_service.send_email(
                to_email=user.email,
                to_name=user.full_name,
                subject=subject,
                template_name=event.value,
                context=context,
            )
        except Exception as e:
            # Falha de e-mail nunca propaga — loga e continua
            logger.error(
                "notification.send_failed",
                notification_event=event.value,
                user_id=str(user.id),
                subscription_id=str(subscription.id),
                error=str(e),
            )

    # ------------------------------------------------------------------ #
    # Métodos públicos para cada evento                                  #
    # ------------------------------------------------------------------ #

    async def notify_payment_approved(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.PAYMENT_APPROVED)

    async def notify_payment_failed(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.PAYMENT_FAILED)

    async def notify_renewal_success(self, user: User, subscription: Subscription) -> None:
        next_renewal = subscription.current_period_end.strftime("%d/%m/%Y")
        await self._send(
            user,
            subscription,
            SubscriptionEmailEvent.RENEWAL_SUCCESS,
            {"next_renewal": next_renewal},
        )

    async def notify_renewal_reminder(self, user: User, subscription: Subscription) -> None:
        # Comparar por data para evitar erro de arredondamento
        days_left = (subscription.current_period_end.date() - datetime.now().date()).days
        if days_left > settings.RENEWAL_REMINDER_DAYS_BEFORE:
            return  # Ainda não é o momento

        await self._send(
            user,
            subscription,
            SubscriptionEmailEvent.RENEWAL_REMINDER,
            {"days_left": days_left},
        )

    async def notify_cancellation(self, user: User, subscription: Subscription) -> None:
        expiration_date = subscription.current_period_end.strftime("%d/%m/%Y")
        await self._send(
            user,
            subscription,
            SubscriptionEmailEvent.CANCELLATION,
            {"expiration_date": expiration_date},
        )

    async def notify_reactivation(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.REACTIVATION)

    async def notify_plan_change(
        self,
        user: User,
        subscription: Subscription,
        old_plan_name: str,
    ) -> None:
        await self._send(
            user,
            subscription,
            SubscriptionEmailEvent.PLAN_CHANGE,
            {
                "old_plan": old_plan_name,
                "new_plan": subscription.plan.name,
                "new_amount": subscription.plan.price_cents / 100,
            },
        )

    async def notify_dunning_recovered(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.DUNNING_RECOVERED)

    async def notify_dunning_retry_failed(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.DUNNING_RETRY_FAILED)

    async def notify_dunning_expired(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.DUNNING_EXPIRED)