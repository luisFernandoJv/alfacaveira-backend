"""Repositório de acesso a dados de `SubscriptionHistory`.

Append-only por natureza (é um log de auditoria): expõe apenas leitura +
`add` (herdado de `BaseRepository`) — nenhum método de update/delete é
necessário nem deve ser adicionado aqui.
"""

import uuid

from sqlalchemy import select

from app.models.billing.subscription_history import SubscriptionHistory
from app.repositories.base import BaseRepository


class SubscriptionHistoryRepository(BaseRepository[SubscriptionHistory]):
    model = SubscriptionHistory

    async def list_by_subscription(self, subscription_id: uuid.UUID) -> list[SubscriptionHistory]:
        stmt = (
            select(SubscriptionHistory)
            .where(SubscriptionHistory.subscription_id == subscription_id)
            .order_by(SubscriptionHistory.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_subscription_and_payment(
        self, subscription_id: uuid.UUID, payment_id: uuid.UUID
    ) -> SubscriptionHistory | None:
        """Usado por `SubscriptionService.renew_subscription` (ADR-023) para
        checar, antes do CAS, se este `payment_id` já gerou uma renovação
        para esta assinatura — checagem aplicativa; o índice único parcial
        `ux_subscription_history_payment` (migration 0008) é o backstop
        final contra a janela entre esta leitura e o `INSERT` sob corrida
        real."""
        stmt = select(SubscriptionHistory).where(
            SubscriptionHistory.subscription_id == subscription_id,
            SubscriptionHistory.payment_id == payment_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest(self, subscription_id: uuid.UUID) -> SubscriptionHistory | None:
        """Entrada mais recente desta assinatura, ou `None`. Leitura de
        propósito geral (ex.: telas de auditoria/portal do assinante) —
        avaliada durante o ADR-023 como base para um guard de debounce em
        `change_plan`, mas não usada para isso no final: as proteções já
        existentes (CAS + guard "já está neste plano") cobrem o risco de
        duplicação sem precisar desta consulta. Mantida por ser um método
        de leitura correto e genericamente útil."""
        stmt = (
            select(SubscriptionHistory)
            .where(SubscriptionHistory.subscription_id == subscription_id)
            .order_by(SubscriptionHistory.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()