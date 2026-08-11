"""Regras de negócio administrativas de `Plan`, `Feature` e `PlanFeature`.

SEM CACHE TEMPORARIAMENTE — até a serialização ser corrigida.
"""

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import get_cache
from app.core.exceptions import ConflictError, NotFoundError, ValidationDomainError
from app.database.uow import UnitOfWork
from app.models.billing.feature import Feature
from app.models.billing.plan import Plan
from app.models.billing.plan_feature import PlanFeature
from app.models.enums import BillingPeriod, FeatureKey, FeatureKind
from app.repositories.billing.feature_repository import FeatureRepository
from app.repositories.billing.plan_repository import PlanRepository
import structlog

logger = structlog.get_logger(__name__)

# TTL para cache de planos e features (1 hora)
CACHE_TTL_SECONDS = 3600


class PlanService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = PlanRepository(session)
        self._features = FeatureRepository(session)

    # ==================================================================== #
    # LEITURA — SEM CACHE (TEMPORÁRIO)                                     #
    # ==================================================================== #

    async def get_plan(self, plan_id: uuid.UUID) -> Plan:
        """Busca um plano pelo ID — SEM CACHE (temporário)."""
        # cache = get_cache()
        # cache_key = f"plan:{plan_id}"
        # if cache:
        #     cached = await cache.get(cache_key)
        #     if cached:
        #         logger.debug("plan.cache_hit", plan_id=str(plan_id))
        #         return cached

        plan = await self._plans.get_with_features(plan_id)
        if plan is None:
            raise NotFoundError("Plano não encontrado.")

        # if cache and plan:
        #     await cache.set(cache_key, plan, ttl=CACHE_TTL_SECONDS)

        return plan

    async def list_plans(self) -> list[Plan]:
        """Lista planos ativos — SEM CACHE (temporário)."""
        # cache = get_cache()
        # cache_key = "plans:active"
        # if cache:
        #     cached = await cache.get(cache_key)
        #     if cached is not None:
        #         logger.debug("plans.cache_hit")
        #         return cached

        plans = await self._plans.list_active()

        # if cache and plans:
        #     await cache.set(cache_key, plans, ttl=CACHE_TTL_SECONDS)

        return plans

    async def get_plan_by_slug(self, slug: str) -> Plan:
        """Busca um plano pelo slug — SEM CACHE (temporário)."""
        # cache = get_cache()
        # cache_key = f"plan:slug:{slug}"
        # if cache:
        #     cached = await cache.get(cache_key)
        #     if cached:
        #         logger.debug("plan.slug.cache_hit", slug=slug)
        #         return cached

        plan = await self._plans.get_by_slug_with_features(slug)
        if plan is None:
            raise NotFoundError(f"Plano '{slug}' não encontrado.")

        # if cache and plan:
        #     await cache.set(cache_key, plan, ttl=CACHE_TTL_SECONDS)

        return plan

    async def list_features(self) -> list[Feature]:
        """Lista features ativas — SEM CACHE (temporário)."""
        # cache = get_cache()
        # cache_key = "features:active"
        # if cache:
        #     cached = await cache.get(cache_key)
        #     if cached is not None:
        #         logger.debug("features.cache_hit")
        #         return cached

        features = await self._features.list_active()

        # if cache and features:
        #     await cache.set(cache_key, features, ttl=CACHE_TTL_SECONDS)

        return features

    async def invalidate_plan_cache(self, plan_id: Optional[uuid.UUID] = None) -> None:
        """Invalida o cache de planos."""
        cache = get_cache()
        if cache is None:
            return

        if plan_id:
            await cache.delete(f"plan:{plan_id}")
        await cache.clear_pattern("plan:slug:*")
        await cache.delete("plans:active")
        await cache.delete("plans:all")
        await cache.delete("features:active")
        logger.info("plan.cache_invalidated", plan_id=str(plan_id) if plan_id else "all")

    # ==================================================================== #
    # ESCRITA (inalterada)                                                 #
    # ==================================================================== #

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

        await self.invalidate_plan_cache()
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

        await self.invalidate_plan_cache(plan_id)
        return await self.get_plan(plan_id)

    async def set_plan_feature(
        self,
        *,
        plan_id: uuid.UUID,
        feature_key: FeatureKey,
        quota_limit: int | None = None,
    ) -> Plan:
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

        await self.invalidate_plan_cache(plan_id)
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

        await self.invalidate_plan_cache(plan_id)
        return await self.get_plan(plan_id)

    async def create_feature(
        self,
        *,
        key: FeatureKey,
        kind: FeatureKind,
        name: str,
        description: str | None = None,
        is_active: bool = True,
    ) -> Feature:
        existing = await self._features.get_by_key(key)
        if existing is not None:
            raise ConflictError(f"Feature '{key.value}' já existe.")

        feature = Feature(
            key=key,
            kind=kind,
            name=name,
            description=description,
            is_active=is_active,
        )
        async with UnitOfWork(self._session):
            await self._features.add(feature)

        await self.invalidate_plan_cache()
        return feature

    async def _rebuild_features_cache(self, plan_id: uuid.UUID) -> None:
        """Reconstrói `Plan.features` (JSONB) a partir de `PlanFeature`."""
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