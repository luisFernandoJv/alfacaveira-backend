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