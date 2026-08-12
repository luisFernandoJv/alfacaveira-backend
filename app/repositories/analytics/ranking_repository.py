"""Repositório de acesso a dados de `UserRanking`."""

import uuid
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.models.analytics.ranking import UserRanking
from app.repositories.base import BaseRepository

_RELATIONS = (selectinload(UserRanking.user),)


class RankingRepository(BaseRepository[UserRanking]):
    """Repositório de ranking de usuários."""

    model = UserRanking

    async def get_by_user(self, user_id: uuid.UUID) -> UserRanking | None:
        """Busca ranking de um usuário específico com suas métricas."""
        stmt = (
            select(UserRanking)
            .where(UserRanking.user_id == user_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_global_ranking(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserRanking]:
        """Retorna ranking global ordenado por posição."""
        stmt = (
            select(UserRanking)
            .where(UserRanking.total_points > 0)
            .options(*_RELATIONS)
            .order_by(UserRanking.rank.asc(), UserRanking.total_points.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_weekly_ranking(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserRanking]:
        """Retorna ranking semanal."""
        stmt = (
            select(UserRanking)
            .where(UserRanking.weekly_points > 0)
            .options(*_RELATIONS)
            .order_by(UserRanking.weekly_points.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_monthly_ranking(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserRanking]:
        """Retorna ranking mensal."""
        stmt = (
            select(UserRanking)
            .where(UserRanking.monthly_points > 0)
            .options(*_RELATIONS)
            .order_by(UserRanking.monthly_points.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_user_position(self, user_id: uuid.UUID) -> int | None:
        """Retorna a posição global do usuário."""
        ranking = await self.get_by_user(user_id)
        return ranking.rank if ranking else None

    async def upsert(self, user_id: uuid.UUID, **fields) -> UserRanking:
        """Cria ou atualiza o ranking de um usuário."""
        existing = await self.get_by_user(user_id)

        if existing:
            for key, value in fields.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await self.session.flush()
            return existing

        ranking = UserRanking(user_id=user_id, **fields)
        self.session.add(ranking)
        await self.session.flush()
        return ranking

    async def update_rankings(self) -> None:
        """
        Atualiza as posições de todos os usuários no ranking global.

        Usa ROW_NUMBER() para calcular posições de forma eficiente.
        """
        # Atualiza ranking global
        await self.session.execute(
            text("""
                WITH ranked AS (
                    SELECT 
                        id,
                        ROW_NUMBER() OVER (ORDER BY total_points DESC) as new_rank
                    FROM user_rankings
                    WHERE total_points > 0
                )
                UPDATE user_rankings
                SET rank = ranked.new_rank,
                    updated_at = NOW()
                FROM ranked
                WHERE user_rankings.id = ranked.id
            """)
        )

        # Atualiza ranking semanal
        await self.session.execute(
            text("""
                WITH ranked AS (
                    SELECT 
                        id,
                        ROW_NUMBER() OVER (ORDER BY weekly_points DESC) as new_rank
                    FROM user_rankings
                    WHERE weekly_points > 0
                )
                UPDATE user_rankings
                SET rank_weekly = ranked.new_rank,
                    updated_at = NOW()
                FROM ranked
                WHERE user_rankings.id = ranked.id
            """)
        )

        # Atualiza ranking mensal
        await self.session.execute(
            text("""
                WITH ranked AS (
                    SELECT 
                        id,
                        ROW_NUMBER() OVER (ORDER BY monthly_points DESC) as new_rank
                    FROM user_rankings
                    WHERE monthly_points > 0
                )
                UPDATE user_rankings
                SET rank_monthly = ranked.new_rank,
                    updated_at = NOW()
                FROM ranked
                WHERE user_rankings.id = ranked.id
            """)
        )

        await self.session.flush()

    async def get_count(self) -> int:
        """Retorna o número total de usuários no ranking."""
        stmt = select(func.count()).select_from(UserRanking).where(UserRanking.total_points > 0)
        result = await self.session.execute(stmt)
        return result.scalar() or 0