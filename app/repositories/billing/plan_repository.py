"""Repositório de acesso a dados de `Plan`.

Tabela pequena (3-5 linhas: FREE/STANDARD/PRO), sem paginação cursor-based —
mesmo raciocínio de `DisciplineRepository`. `get_by_slug` é a query mais
usada: resolve o plano FREE default para usuários sem assinatura ativa
(`FeatureGateService`, Etapa 3).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.billing.plan import Plan
from app.models.billing.plan_feature import PlanFeature
from app.repositories.base import BaseRepository

# `selectinload` de `plan_features.feature` evita N+1 ao materializar o cache
# `Plan.features` (JSONB) a partir da fonte de verdade normalizada.
_WITH_FEATURES = selectinload(Plan.plan_features).selectinload(PlanFeature.feature)


class PlanRepository(BaseRepository[Plan]):
    model = Plan

    async def get_by_slug(self, slug: str) -> Plan | None:
        stmt = select(Plan).where(Plan.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_features(self, plan_id: uuid.UUID) -> Plan | None:
        stmt = select(Plan).where(Plan.id == plan_id).options(_WITH_FEATURES)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug_with_features(self, slug: str) -> Plan | None:
        stmt = select(Plan).where(Plan.slug == slug).options(_WITH_FEATURES)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Plan]:
        stmt = (
            select(Plan)
            .where(Plan.is_active.is_(True))
            .options(_WITH_FEATURES)
            .order_by(Plan.price_cents.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())