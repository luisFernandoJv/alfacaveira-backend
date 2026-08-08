"""Regras de negócio de `Subscription`: criar, cancelar, reativar, renovar e
trocar de plano.

Toda transição de status ou de plano grava uma linha em `SubscriptionHistory`
dentro da mesma `UnitOfWork` que altera a `Subscription` — nunca separado. A
regra "no máximo 1 assinatura ATIVA por usuário" é garantida em duas camadas:
checagem otimista aqui (mensagem de erro amigável) + índice único parcial
`ux_subscriptions_one_active_per_user` no banco (migration 0005) como
garantia final contra corrida.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.billing.subscription import Subscription
from app.models.billing.subscription_history import SubscriptionHistory
from app.models.enums import BillingPeriod, SubscriptionHistoryReason, SubscriptionStatus
from app.repositories.billing.plan_repository import PlanRepository
from app.repositories.billing.subscription_repository import SubscriptionRepository

_PERIOD_LENGTH: dict[BillingPeriod, timedelta] = {
    BillingPeriod.MENSAL: timedelta(days=30),
    BillingPeriod.SEMESTRAL: timedelta(days=182),
    BillingPeriod.ANUAL: timedelta(days=365),
}


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._subscriptions = SubscriptionRepository(session)
        self._plans = PlanRepository(session)

    # ------------------------------------------------------------------ #
    # Leitura
    # ------------------------------------------------------------------ #

    async def get_subscription(self, subscription_id: uuid.UUID, user_id: uuid.UUID) -> Subscription:
        subscription = await self._subscriptions.get_owned(subscription_id, user_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        return subscription

    async def get_active(self, user_id: uuid.UUID) -> Subscription | None:
        return await self._subscriptions.get_active_by_user(user_id)

    async def list_subscriptions(self, user_id: uuid.UUID) -> list[Subscription]:
        return await self._subscriptions.list_by_user(user_id)

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #

    async def create_subscription(self, user_id: uuid.UUID, plan_id: uuid.UUID) -> Subscription:
        if await self._subscriptions.get_active_by_user(user_id) is not None:
            raise ConflictError("Usuário já possui uma assinatura ativa.")

        plan = await self._plans.get_by_id(plan_id)
        if plan is None or not plan.is_active:
            raise NotFoundError("Plano não encontrado ou inativo.")

        now = _utcnow()
        subscription = Subscription(
            user_id=user_id,
            plan_id=plan.id,
            status=SubscriptionStatus.ATIVA,
            current_period_start=now,
            current_period_end=now + _PERIOD_LENGTH[plan.billing_period],
            cancel_at_period_end=False,
        )

        try:
            async with UnitOfWork(self._session):
                await self._subscriptions.add(subscription)
                await self._session.flush()
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=None,
                        to_plan_id=plan.id,
                        from_status=None,
                        to_status=SubscriptionStatus.ATIVA,
                        reason=SubscriptionHistoryReason.CRIADA,
                    )
                )
                await self._session.flush()
        except IntegrityError as exc:
            # Backstop contra corrida: duas requisições concorrentes tentando
            # criar a assinatura ativa do mesmo usuário. A checagem acima já
            # cobre o caso comum; isto cobre a janela entre checagem e commit.
            raise ConflictError("Usuário já possui uma assinatura ativa.") from exc

        return await self.get_subscription(subscription.id, user_id)

    async def cancel_subscription(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID, *, immediately: bool = False
    ) -> Subscription:
        subscription = await self.get_subscription(subscription_id, user_id)
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Apenas assinaturas ativas podem ser canceladas.")

        async with UnitOfWork(self._session):
            previous_status = subscription.status
            if immediately:
                subscription.status = SubscriptionStatus.CANCELADA
            subscription.cancel_at_period_end = True
            self._session.add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    from_plan_id=subscription.plan_id,
                    to_plan_id=subscription.plan_id,
                    from_status=previous_status,
                    to_status=subscription.status,
                    reason=SubscriptionHistoryReason.CANCELADA,
                )
            )
            await self._session.flush()

        return await self.get_subscription(subscription_id, user_id)

    async def reactivate_subscription(self, subscription_id: uuid.UUID, user_id: uuid.UUID) -> Subscription:
        """Desfaz um cancelamento agendado (`cancel_at_period_end`) antes do
        fim do período — a assinatura segue ATIVA sem interrupção.
        """
        subscription = await self.get_subscription(subscription_id, user_id)
        if subscription.status != SubscriptionStatus.ATIVA or not subscription.cancel_at_period_end:
            raise ConflictError("Esta assinatura não está agendada para cancelamento.")

        async with UnitOfWork(self._session):
            subscription.cancel_at_period_end = False
            self._session.add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    from_plan_id=subscription.plan_id,
                    to_plan_id=subscription.plan_id,
                    from_status=SubscriptionStatus.ATIVA,
                    to_status=SubscriptionStatus.ATIVA,
                    reason=SubscriptionHistoryReason.REATIVADA,
                )
            )
            await self._session.flush()

        return await self.get_subscription(subscription_id, user_id)

    async def renew_subscription(self, subscription_id: uuid.UUID, user_id: uuid.UUID) -> Subscription:
        """Avança o período da assinatura após confirmação de pagamento
        (chamado por `PaymentService`, não diretamente por um endpoint).
        """
        subscription = await self.get_subscription(subscription_id, user_id)
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Apenas assinaturas ativas podem ser renovadas.")

        async with UnitOfWork(self._session):
            period_length = _PERIOD_LENGTH[subscription.plan.billing_period]
            subscription.current_period_start = subscription.current_period_end
            subscription.current_period_end = subscription.current_period_end + period_length
            self._session.add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    from_plan_id=subscription.plan_id,
                    to_plan_id=subscription.plan_id,
                    from_status=SubscriptionStatus.ATIVA,
                    to_status=SubscriptionStatus.ATIVA,
                    reason=SubscriptionHistoryReason.RENOVADA,
                )
            )
            await self._session.flush()

        return await self.get_subscription(subscription_id, user_id)

    async def change_plan(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID, new_plan_id: uuid.UUID
    ) -> Subscription:
        """Upgrade ou downgrade — decidido automaticamente comparando
        `price_cents` do plano atual com o novo.
        """
        subscription = await self.get_subscription(subscription_id, user_id)
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Apenas assinaturas ativas podem trocar de plano.")

        new_plan = await self._plans.get_by_id(new_plan_id)
        if new_plan is None or not new_plan.is_active:
            raise NotFoundError("Plano não encontrado ou inativo.")
        if new_plan.id == subscription.plan_id:
            raise ConflictError("A assinatura já está neste plano.")

        reason = (
            SubscriptionHistoryReason.UPGRADE
            if new_plan.price_cents > subscription.plan.price_cents
            else SubscriptionHistoryReason.DOWNGRADE
        )
        old_plan_id = subscription.plan_id

        async with UnitOfWork(self._session):
            subscription.plan_id = new_plan.id
            self._session.add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    from_plan_id=old_plan_id,
                    to_plan_id=new_plan.id,
                    from_status=SubscriptionStatus.ATIVA,
                    to_status=SubscriptionStatus.ATIVA,
                    reason=reason,
                )
            )
            await self._session.flush()

        return await self.get_subscription(subscription_id, user_id)

    async def mark_payment_failed(self, subscription_id: uuid.UUID) -> Subscription:
        """Chamado por `PaymentService` quando um pagamento é recusado ou
        estornado — não exige `user_id` porque quem aciona é o processamento
        de webhook, não uma requisição autenticada do usuário.
        """
        subscription = await self._subscriptions.get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")

        async with UnitOfWork(self._session):
            previous_status = subscription.status
            subscription.status = SubscriptionStatus.INADIMPLENTE
            self._session.add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    from_plan_id=subscription.plan_id,
                    to_plan_id=subscription.plan_id,
                    from_status=previous_status,
                    to_status=SubscriptionStatus.INADIMPLENTE,
                    reason=SubscriptionHistoryReason.PAGAMENTO_FALHOU,
                )
            )
            await self._session.flush()

        return subscription

    async def expire_subscription(self, subscription_id: uuid.UUID) -> Subscription:
        """Chamado por um job agendado (fora do escopo desta etapa) quando o
        período termina sem renovação.
        """
        subscription = await self._subscriptions.get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Apenas assinaturas ativas podem expirar.")

        async with UnitOfWork(self._session):
            subscription.status = SubscriptionStatus.EXPIRADA
            self._session.add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    from_plan_id=subscription.plan_id,
                    to_plan_id=subscription.plan_id,
                    from_status=SubscriptionStatus.ATIVA,
                    to_status=SubscriptionStatus.EXPIRADA,
                    reason=SubscriptionHistoryReason.EXPIRADA,
                )
            )
            await self._session.flush()

        return subscription


def _utcnow() -> datetime:
    return datetime.now(UTC)
