"""Regras de negócio de `Payment`: iniciar uma cobrança via `PaymentGateway`
e processar a confirmação assíncrona (webhook) de forma idempotente.

`PaymentRepository.get_by_provider_payment_id` é a base da idempotência: se o
evento do provedor já foi registrado com o mesmo status, `process_webhook_event`
não reprocessa — importante porque retry de evento é padrão em gateways de
pagamento reais. O parsing/validação de assinatura do payload do webhook fica
para a Etapa 4 (`app/api/v1/billing/webhooks.py`); este service só recebe
`provider_payment_id` + `status` já extraídos.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database.uow import UnitOfWork
from app.models.billing.payment import Payment
from app.models.enums import PaymentStatus
from app.repositories.billing.payment_repository import PaymentRepository
from app.repositories.billing.subscription_repository import SubscriptionRepository
from app.services.billing.gateway import PaymentGateway, get_payment_gateway
from app.services.billing.subscription_service import SubscriptionService


class PaymentService:
    def __init__(self, session: AsyncSession, gateway: PaymentGateway | None = None) -> None:
        self._session = session
        self._payments = PaymentRepository(session)
        self._subscriptions = SubscriptionRepository(session)
        self._gateway = gateway or get_payment_gateway()
        # Composição, não herança: reaproveita as transições de status já
        # centralizadas em `SubscriptionService` (ex.: `mark_payment_failed`)
        # em vez de duplicar a lógica de `SubscriptionHistory` aqui.
        self._subscription_service = SubscriptionService(session)

    async def list_by_subscription(self, subscription_id: uuid.UUID) -> list[Payment]:
        return await self._payments.list_by_subscription(subscription_id)

    async def charge_subscription(self, subscription_id: uuid.UUID) -> Payment:
        """Inicia a cobrança do período corrente/próximo de uma assinatura,
        via o `PaymentGateway` configurado (`PAYMENT_GATEWAY_DRIVER`).
        """
        subscription = await self._subscriptions.get_by_id_with_plan(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")

        result = await self._gateway.charge(
            amount_cents=subscription.plan.price_cents,
            currency="BRL",
            subscription_id=subscription.id,
        )

        payment = Payment(
            subscription_id=subscription.id,
            amount_cents=subscription.plan.price_cents,
            currency="BRL",
            status=result.status,
            provider=result.provider,
            provider_payment_id=result.provider_payment_id,
            paid_at=_utcnow() if result.status == PaymentStatus.APROVADO else None,
        )

        async with UnitOfWork(self._session):
            await self._payments.add(payment)

        return payment

    async def process_webhook_event(self, *, provider_payment_id: str, status: PaymentStatus) -> Payment:
        """Aplica a confirmação de um evento de webhook a um `Payment` já
        registrado por `charge_subscription`.

        Idempotente: se o pagamento já está neste status, retorna sem
        reprocessar (nem duplica efeito colateral na assinatura).
        """
        payment = await self._payments.get_by_provider_payment_id(provider_payment_id)
        if payment is None:
            raise NotFoundError(
                f"Pagamento com provider_payment_id '{provider_payment_id}' não encontrado."
            )
        if payment.status == status:
            return payment

        async with UnitOfWork(self._session):
            payment.status = status
            if status == PaymentStatus.APROVADO:
                payment.paid_at = _utcnow()
            await self._session.flush()

        if status in (PaymentStatus.RECUSADO, PaymentStatus.ESTORNADO):
            await self._subscription_service.mark_payment_failed(payment.subscription_id)

        return payment


def _utcnow() -> datetime:
    return datetime.now(UTC)
