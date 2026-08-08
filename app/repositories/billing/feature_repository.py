"""Repositório de acesso a dados de `Feature` (catálogo de permissões).

Tabela pequena e praticamente estática (cresce só quando uma nova permissão
é adicionada ao produto) — sem paginação cursor-based.
"""

from sqlalchemy import select

from app.models.billing.feature import Feature
from app.models.enums import FeatureKey
from app.repositories.base import BaseRepository


class FeatureRepository(BaseRepository[Feature]):
    model = Feature

    async def get_by_key(self, key: FeatureKey) -> Feature | None:
        stmt = select(Feature).where(Feature.key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Feature]:
        stmt = select(Feature).where(Feature.is_active.is_(True)).order_by(Feature.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())