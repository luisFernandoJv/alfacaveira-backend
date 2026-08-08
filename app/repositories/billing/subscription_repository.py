"""Repositório de acesso a dados de `Subscription`.

`get_active_by_user` é a query mais executada do módulo — roda a cada
verificação de `FeatureGateService` (potencialmente em todo request de
outros contextos), por isso já carrega o plano com suas features via
`selectinload` (evita N+1 no gate) e se apoia no índice
`ix_subscriptions_status`/`ix_subscriptions_user_id` já existentes.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.billing.plan import Plan
from app.models.billing.plan_feature import PlanFeature
from app.models.billing.subscription import Subscription
from app.models.enums import SubscriptionStatus
from app.repositories.base import BaseRepository

_WITH_PLAN = selectinload(Subscription.plan).selectinload(Plan.plan_features).selectinload(
    PlanFeature.feature
)
_WITH_PLAN_AND_HISTORY = (_WITH_PLAN, selectinload(Subscription.history))


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    async def get_active_by_user(self, user_id: uuid.UUID) -> Subscription | None:
        """Assinatura ATIVA do usuário, se houver.

        `None` significa "sem assinatura paga" — o usuário está no plano
        FREE por convenção (nunca há linha em `subscriptions` para FREE).
        O índice único parcial `ux_subscriptions_one_active_per_user`
        (migration 0005) garante que este resultado é sempre 0 ou 1 linha.
        """
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ATIVA,
            )
            .options(_WITH_PLAN)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_plan(self, subscription_id: uuid.UUID) -> Subscription | None:
        """Busca por id (sem exigir `user_id`), com o plano e suas features
        já carregados — mesmo `selectinload` de `get_active_by_user`. Usada
        por `PaymentService.charge_subscription`, que já resolveu a posse da
        assinatura antes de chamar isto (não é um método de leitura exposta
        diretamente a partir de um endpoint escopado ao usuário).
        """
        stmt = select(Subscription).where(Subscription.id == subscription_id).options(_WITH_PLAN)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID
    ) -> Subscription | None:
        """Busca por id, restrita ao dono — usada antes de cancelar/alterar."""
        stmt = (
            select(Subscription)
            .where(Subscription.id == subscription_id, Subscription.user_id == user_id)
            .options(*_WITH_PLAN_AND_HISTORY)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID) -> list[Subscription]:
        """Histórico completo de assinaturas do usuário (ativas, canceladas,
        expiradas), mais recente primeiro. Volume baixo por usuário — sem
        paginação cursor-based, mesmo raciocínio de `DisciplineRepository`.
        """
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .options(_WITH_PLAN)
            .order_by(Subscription.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())