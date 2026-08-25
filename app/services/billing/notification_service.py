"""Notificações transacionais de assinatura: e-mail + sininho."""

from datetime import datetime
from typing import Optional

import structlog

from app.core.config import settings
from app.models.billing.subscription import Subscription
from app.models.enums import NotificationCategory, SubscriptionEmailEvent
from app.models.identity.user import User
from app.services.identity.email_service import EmailService
from app.services.platform.notification_service import NotificationService

logger = structlog.get_logger(__name__)


class SubscriptionNotificationService:
    """Entrega o mesmo evento por e-mail e in-app, quando aplicável."""

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

    _IN_APP_TITLES = {
        SubscriptionEmailEvent.PAYMENT_APPROVED: "Pagamento aprovado",
        SubscriptionEmailEvent.PAYMENT_FAILED: "Falha no pagamento",
        SubscriptionEmailEvent.RENEWAL_SUCCESS: "Renovação realizada",
        SubscriptionEmailEvent.RENEWAL_REMINDER: "Renovação em breve",
        SubscriptionEmailEvent.CANCELLATION: "Plano cancelado",
        SubscriptionEmailEvent.REACTIVATION: "Plano reativado",
        SubscriptionEmailEvent.PLAN_CHANGE: "Plano alterado",
        SubscriptionEmailEvent.DUNNING_RECOVERED: "Pagamento regularizado",
        SubscriptionEmailEvent.DUNNING_RETRY_FAILED: "Nova falha no pagamento",
        SubscriptionEmailEvent.DUNNING_EXPIRED: "Plano expirado",
    }

    def __init__(
        self,
        email_service: Optional[EmailService] = None,
        notification_service: Optional[NotificationService] = None,
    ):
        self._email_service = email_service or EmailService()
        self._notification_service = notification_service

    def _should_send_email(self, event: SubscriptionEmailEvent) -> bool:
        flag_name = self._FLAG_MAP.get(event)
        return bool(flag_name and getattr(settings, flag_name, True))

    def _get_subject(self, event: SubscriptionEmailEvent) -> str:
        return self._SUBJECT_MAP.get(event, "Atualização — Alfa Caveira")

    def _get_first_name(self, user: User) -> str:
        return user.full_name.split(" ")[0] if user.full_name else ""

    def _build_context(
        self,
        subscription: Subscription,
        user: User,
        **extra,
    ) -> dict:
        context = {
            "first_name": self._get_first_name(user),
            "plan_name": subscription.plan.name,
            "amount": subscription.plan.price_cents / 100,
        }
        context.update(extra)
        return context

    async def _send_in_app(
        self,
        user: User,
        subscription: Subscription,
        event: SubscriptionEmailEvent,
        *,
        extra_context: Optional[dict] = None,
    ) -> None:
        if self._notification_service is None:
            return

        extra = extra_context or {}
        title = self._IN_APP_TITLES[event]
        body_by_event = {
            SubscriptionEmailEvent.PAYMENT_APPROVED: f"Seu pagamento do plano {subscription.plan.name} foi aprovado.",
            SubscriptionEmailEvent.PAYMENT_FAILED: f"Não foi possível processar o pagamento do plano {subscription.plan.name}.",
            SubscriptionEmailEvent.RENEWAL_SUCCESS: f"Seu plano {subscription.plan.name} foi renovado com sucesso.",
            SubscriptionEmailEvent.RENEWAL_REMINDER: f"Seu plano será renovado em {extra.get('days_left', 0)} dia(s).",
            SubscriptionEmailEvent.CANCELLATION: f"Seu plano foi cancelado. O acesso permanece até {extra.get('expiration_date', 'a data informada')}.",
            SubscriptionEmailEvent.REACTIVATION: f"Seu plano {subscription.plan.name} foi reativado.",
            SubscriptionEmailEvent.PLAN_CHANGE: f"Seu plano mudou de {extra.get('old_plan', 'plano anterior')} para {subscription.plan.name}.",
            SubscriptionEmailEvent.DUNNING_RECOVERED: f"O pagamento do plano {subscription.plan.name} foi regularizado.",
            SubscriptionEmailEvent.DUNNING_RETRY_FAILED: "Uma nova tentativa de pagamento falhou. Atualize a forma de pagamento para evitar a perda do acesso.",
            SubscriptionEmailEvent.DUNNING_EXPIRED: f"O período de tolerância do plano {subscription.plan.name} terminou.",
        }[event]

        try:
            await self._notification_service.notify_billing_event(
                user_id=user.id,
                event_type=event.value,
                title=title,
                body=body_by_event,
                link="/plano",
                payload={
                    "subscription_id": str(subscription.id),
                    "plan_name": subscription.plan.name,
                    **extra,
                },
            )
        except Exception as exc:
            # O evento de cobrança já pode ter sido persistido/confirmado;
            # uma falha no canal in-app não deve desfazer a operação principal.
            # A falha é explícita e observável — nunca vira uma notificação falsa.
            logger.error(
                "notification.in_app_send_failed",
                notification_event=event.value,
                user_id=str(user.id),
                subscription_id=str(subscription.id),
                error=str(exc),
            )

    async def _send(
        self,
        user: User,
        subscription: Subscription,
        event: SubscriptionEmailEvent,
        extra_context: Optional[dict] = None,
    ) -> None:
        context = self._build_context(subscription, user, **(extra_context or {}))

        # O e-mail respeita a preferência do usuário quando há NotificationService.
        should_email = self._should_send_email(event)
        if should_email and self._notification_service is not None:
            should_email = await self._notification_service.is_email_enabled(
                user.id, NotificationCategory.BILLING
            )

        if should_email:
            try:
                await self._email_service.send_email(
                    to_email=user.email,
                    to_name=user.full_name,
                    subject=self._get_subject(event),
                    template_name=event.value,
                    context=context,
                )
            except Exception as exc:
                logger.error(
                    "notification.email_send_failed",
                    notification_event=event.value,
                    user_id=str(user.id),
                    subscription_id=str(subscription.id),
                    error=str(exc),
                )

        await self._send_in_app(
            user, subscription, event, extra_context=extra_context
        )

    async def notify_payment_approved(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.PAYMENT_APPROVED)

    async def notify_payment_failed(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.PAYMENT_FAILED)

    async def notify_renewal_success(self, user: User, subscription: Subscription) -> None:
        next_renewal = subscription.current_period_end.strftime("%d/%m/%Y")
        await self._send(
            user, subscription, SubscriptionEmailEvent.RENEWAL_SUCCESS,
            {"next_renewal": next_renewal},
        )

    async def notify_renewal_reminder(self, user: User, subscription: Subscription) -> None:
        days_left = (subscription.current_period_end.date() - datetime.now().date()).days
        if days_left > settings.RENEWAL_REMINDER_DAYS_BEFORE:
            return
        await self._send(
            user, subscription, SubscriptionEmailEvent.RENEWAL_REMINDER,
            {"days_left": days_left},
        )

    async def notify_cancellation(self, user: User, subscription: Subscription) -> None:
        expiration_date = subscription.current_period_end.strftime("%d/%m/%Y")
        await self._send(
            user, subscription, SubscriptionEmailEvent.CANCELLATION,
            {"expiration_date": expiration_date},
        )

    async def notify_reactivation(self, user: User, subscription: Subscription) -> None:
        await self._send(user, subscription, SubscriptionEmailEvent.REACTIVATION)

    async def notify_plan_change(
        self, user: User, subscription: Subscription, old_plan_name: str
    ) -> None:
        await self._send(
            user, subscription, SubscriptionEmailEvent.PLAN_CHANGE,
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
