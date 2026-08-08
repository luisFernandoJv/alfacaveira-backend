"""Regras de negócio administrativas de `Plan`, `Feature` e `PlanFeature`.

Este é o único service que escreve em `Plan.features` (JSONB): sempre que a
associação plano↔feature muda (`set_plan_feature`/`remove_plan_feature`), o
cache é reconstruído a partir de `PlanFeature` (fonte de verdade) dentro da
mesma transação. Nenhum outro módulo deve escrever nessa coluna.

Leitura de "o usuário X tem acesso à feature Y" nunca passa por aqui — isso é
responsabilidade de `FeatureGateService`, que é o único ponto de leitura que
outros contextos (practice, learning, analytics) podem importar.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, ValidationDomainError
from app.database.uow import UnitOfWork
from app.models.billing.feature import Feature
from app.models.billing.plan import Plan
from app.models.billing.plan_feature import PlanFeature
from app.models.enums import BillingPeriod, FeatureKey, FeatureKind
from app.repositories.billing.feature_repository import FeatureRepository
from app.repositories.billing.plan_repository import PlanRepository


class PlanService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = PlanRepository(session)
        self._features = FeatureRepository(session)

    # ------------------------------------------------------------------ #
    # Leitura
    # ------------------------------------------------------------------ #

    async def get_plan(self, plan_id: uuid.UUID) -> Plan:
        plan = await self._plans.get_with_features(plan_id)
        if plan is None:
            raise NotFoundError("Plano não encontrado.")
        return plan

    async def get_plan_by_slug(self, slug: str) -> Plan:
        plan = await self._plans.get_by_slug_with_features(slug)
        if plan is None:
            raise NotFoundError(f"Plano '{slug}' não encontrado.")
        return plan

    async def list_plans(self) -> list[Plan]:
        return await self._plans.list_active()

    async def list_features(self) -> list[Feature]:
        return await self._features.list_active()

    # ------------------------------------------------------------------ #
    # CRUD administrativo — Plan
    # ------------------------------------------------------------------ #

    async def create_plan(
        self,
        *,
        name: str,
        slug: str,
        price_cents: int,
        billing_period: BillingPeriod,
        is_active: bool = True,
    ) -> Plan:
        if await self._plans.get_by_slug(slug) is not None:
            raise ConflictError(f"Já existe um plano com o slug '{slug}'.")

        plan = Plan(
            name=name,
            slug=slug,
            price_cents=price_cents,
            billing_period=billing_period,
            is_active=is_active,
            features={},
        )
        async with UnitOfWork(self._session):
            await self._plans.add(plan)

        return await self.get_plan(plan.id)

    async def update_plan(
        self,
        plan_id: uuid.UUID,
        *,
        name: str | None = None,
        price_cents: int | None = None,
        billing_period: BillingPeriod | None = None,
        is_active: bool | None = None,
    ) -> Plan:
        plan = await self.get_plan(plan_id)

        async with UnitOfWork(self._session):
            if name is not None:
                plan.name = name
            if price_cents is not None:
                plan.price_cents = price_cents
            if billing_period is not None:
                plan.billing_period = billing_period
            if is_active is not None:
                plan.is_active = is_active
            await self._session.flush()

        return await self.get_plan(plan_id)

    # ------------------------------------------------------------------ #
    # CRUD administrativo — Feature (catálogo)
    # ------------------------------------------------------------------ #

    async def create_feature(
        self,
        *,
        key: FeatureKey,
        kind: FeatureKind,
        name: str,
        description: str | None = None,
        is_active: bool = True,
    ) -> Feature:
        if await self._features.get_by_key(key) is not None:
            raise ConflictError(f"Já existe uma feature com a key '{key.value}'.")

        feature = Feature(key=key, kind=kind, name=name, description=description, is_active=is_active)
        async with UnitOfWork(self._session):
            await self._features.add(feature)

        return feature

    # ------------------------------------------------------------------ #
    # Associação Plan ↔ Feature (mexe no cache `Plan.features`)
    # ------------------------------------------------------------------ #

    async def set_plan_feature(
        self, *, plan_id: uuid.UUID, feature_key: FeatureKey, quota_limit: int | None = None
    ) -> Plan:
        """Concede (ou atualiza a quota de) uma feature para um plano.

        Idempotente: se a associação já existir, apenas atualiza `quota_limit`.
        """
        plan = await self._plans.get_by_id(plan_id)
        if plan is None:
            raise NotFoundError("Plano não encontrado.")

        feature = await self._features.get_by_key(feature_key)
        if feature is None:
            raise NotFoundError(f"Feature '{feature_key.value}' não encontrada.")

        if feature.kind == FeatureKind.BOOLEAN and quota_limit is not None:
            raise ValidationDomainError(
                f"Feature '{feature_key.value}' é booleana e não aceita quota_limit."
            )

        stmt = select(PlanFeature).where(
            PlanFeature.plan_id == plan_id, PlanFeature.feature_id == feature.id
        )
        result = await self._session.execute(stmt)
        plan_feature = result.scalar_one_or_none()

        async with UnitOfWork(self._session):
            if plan_feature is not None:
                plan_feature.quota_limit = quota_limit
            else:
                self._session.add(
                    PlanFeature(plan_id=plan.id, feature_id=feature.id, quota_limit=quota_limit)
                )
            await self._session.flush()
            await self._rebuild_features_cache(plan_id)

        return await self.get_plan(plan_id)

    async def remove_plan_feature(self, *, plan_id: uuid.UUID, feature_key: FeatureKey) -> Plan:
        feature = await self._features.get_by_key(feature_key)
        if feature is None:
            raise NotFoundError(f"Feature '{feature_key.value}' não encontrada.")

        stmt = select(PlanFeature).where(
            PlanFeature.plan_id == plan_id, PlanFeature.feature_id == feature.id
        )
        result = await self._session.execute(stmt)
        plan_feature = result.scalar_one_or_none()
        if plan_feature is None:
            raise NotFoundError("Este plano não possui essa feature associada.")

        async with UnitOfWork(self._session):
            await self._session.delete(plan_feature)
            await self._session.flush()
            await self._rebuild_features_cache(plan_id)

        return await self.get_plan(plan_id)

    async def _rebuild_features_cache(self, plan_id: uuid.UUID) -> None:
        """Reconstrói `Plan.features` (JSONB) a partir de `PlanFeature`
        (fonte de verdade). Sempre chamado dentro da mesma `UnitOfWork` que
        alterou a associação, nunca isoladamente.
        """
        stmt = (
            select(PlanFeature)
            .where(PlanFeature.plan_id == plan_id)
            .options(selectinload(PlanFeature.feature))
        )
        result = await self._session.execute(stmt)
        plan_features = result.scalars().all()

        cache = {
            pf.feature.key.value: {"kind": pf.feature.kind.value, "quota_limit": pf.quota_limit}
            for pf in plan_features
        }

        plan = await self._session.get(Plan, plan_id)
        plan.features = cache
        await self._session.flush()
