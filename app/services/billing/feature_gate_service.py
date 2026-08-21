"""Único ponto de leitura de "o usuário X tem direito à feature Y" que
módulos fora de `billing` podem importar (`practice`, `learning`,
`analytics`, etc.). Nenhum outro módulo deve importar `Plan`, `Subscription`
ou `PlanFeature` diretamente — só conhece `FeatureKey` (enum) e este service.

Resolução do plano efetivo do usuário:
    assinatura ATIVA (`SubscriptionRepository.get_active_by_user`) → o plano
    dela; sem assinatura ativa → plano FREE (`FREE_PLAN_SLUG`), por
    convenção nunca representado por uma linha em `subscriptions`.

Decisão registrada no doc de acompanhamento: sem dependência de Redis por
enquanto — a leitura já é uma única query com `selectinload` (sem N+1) via
`SubscriptionRepository.get_active_by_user`/`PlanRepository.
get_by_slug_with_features`. Cache entra só se isso aparecer como gargalo real
(KISS/YAGNI).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.billing.plan import Plan
from app.models.billing.plan_feature import PlanFeature
from app.models.enums import FeatureKey
from app.repositories.billing.plan_repository import PlanRepository
from app.repositories.billing.subscription_repository import SubscriptionRepository

# Plano concedido a todo usuário sem assinatura paga. Precisa existir no
# banco com este slug exato (seed dos planos — Etapa 6); se não existir,
# `get_effective_plan` levanta `NotFoundError` de propósito, em vez de
# assumir silenciosamente "sem features", para deixar o problema de
# configuração óbvio em vez de mascarado.
FREE_PLAN_SLUG = "free"


class FeatureGateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._subscriptions = SubscriptionRepository(session)
        self._plans = PlanRepository(session)

    async def get_effective_plan(self, user_id: uuid.UUID) -> Plan:
        """Plano efetivo do usuário: o da assinatura ativa, ou FREE."""
        subscription = await self._subscriptions.get_active_by_user(user_id)
        if subscription is not None:
            return subscription.plan

        plan = await self._plans.get_by_slug_with_features(FREE_PLAN_SLUG)
        if plan is None:
            raise NotFoundError(
                f"Plano padrão '{FREE_PLAN_SLUG}' não está cadastrado. Rode o seed de planos."
            )
        return plan

    async def has_feature(self, user_id: uuid.UUID, key: FeatureKey) -> bool:
        plan = await self.get_effective_plan(user_id)
        return _find_plan_feature(plan, key) is not None

    async def assert_feature(self, user_id: uuid.UUID, key: FeatureKey) -> None:
        """Levanta `ForbiddenError` se o plano efetivo não inclui `key`."""
        if not await self.has_feature(user_id, key):
            raise ForbiddenError(f"Seu plano atual não inclui a feature '{key.value}'.")

    async def get_quota_limit(self, user_id: uuid.UUID, key: FeatureKey) -> int | None:
        """Limite de quota da feature no plano efetivo (`None` = ilimitado).

        Levanta `ForbiddenError` se o plano nem tem acesso à feature — mesmo
        comportamento de `assert_feature`, para quem for chamar isto direto.
        """
        plan = await self.get_effective_plan(user_id)
        plan_feature = _find_plan_feature(plan, key)
        if plan_feature is None:
            raise ForbiddenError(f"Seu plano atual não inclui a feature '{key.value}'.")
        return plan_feature.quota_limit

    async def assert_within_quota(self, user_id: uuid.UUID, key: FeatureKey, current_usage: int) -> None:
        """Levanta `ForbiddenError` se `current_usage` já atingiu o limite do
        plano efetivo para `key`. Uso típico em `practice`/`learning` antes
        de criar um novo registro contado pela quota (ex.: `daily_questions`).
        """
        limit = await self.get_quota_limit(user_id, key)
        if limit is not None and current_usage >= limit:
            raise ForbiddenError(f"Limite do seu plano foi atingido para '{key.value}' ({limit}).")


def _find_plan_feature(plan: Plan, key: FeatureKey) -> PlanFeature | None:
    return next((pf for pf in plan.plan_features if pf.feature.key == key), None)
