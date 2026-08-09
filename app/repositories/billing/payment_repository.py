"""Repositório de acesso a dados de `Payment`.

`get_by_provider_payment_id` é a base da idempotência de negócio no
processamento de webhooks (Etapa 4, `webhooks.py`): se o pagamento do
provedor já foi registrado, o service não processa de novo — mesmo que o
provedor reenvie o evento (retry é padrão em gateways de pagamento).
"""

import uuid
from datetime import datetime

from sqlalchemy import select, update

from app.models.billing.payment import Payment
from app.models.enums import PaymentStatus
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

    async def compare_and_swap_status(
        self,
        payment_id: uuid.UUID,
        *,
        expected_status: PaymentStatus,
        new_status: PaymentStatus,
        paid_at: datetime | None = None,
    ) -> bool:
        """Análogo a `SubscriptionRepository.compare_and_swap_status`
        (mesmo raciocínio de `UPDATE ... WHERE status = :expected_status`
        sob READ COMMITTED, ver o docstring lá para o detalhe) — aqui é a
        base de concorrência real para `PaymentService.process_webhook_event`
        (roadmap item 7, ADR-017): duas entregas concorrentes do mesmo
        evento de webhook (ou de dois eventos diferentes para o mesmo
        `Payment`) só deixam uma vencer a transição; a outra recebe
        `False` e trata como reentrega idempotente.
        """
        values: dict[str, object] = {"status": new_status}
        if paid_at is not None:
            values["paid_at"] = paid_at
        stmt = (
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == expected_status)
            .values(**values)
        )
        result = await self.session.execute(stmt)
        return result.rowcount == 1