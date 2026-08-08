"""Repositório de acesso a dados de `Payment`.

`get_by_provider_payment_id` é a base da idempotência de negócio no
processamento de webhooks (Etapa 4, `webhooks.py`): se o pagamento do
provedor já foi registrado, o service não processa de novo — mesmo que o
provedor reenvie o evento (retry é padrão em gateways de pagamento).
"""

import uuid

from sqlalchemy import select

from app.models.billing.payment import Payment
from app.repositories.base import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    async def get_by_provider_payment_id(self, provider_payment_id: str) -> Payment | None:
        stmt = select(Payment).where(Payment.provider_payment_id == provider_payment_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_subscription(self, subscription_id: uuid.UUID) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(Payment.subscription_id == subscription_id)
            .order_by(Payment.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())