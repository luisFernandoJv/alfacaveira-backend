"""Regras de negócio de ranking."""

import uuid
from datetime import UTC, datetime, date, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.analytics.ranking import UserRanking
from app.repositories.analytics.ranking_repository import RankingRepository
from app.repositories.analytics.user_stats_repository import (
    StudyStreakRepository,
    UserDailyStatRepository,
)


class RankingService:
    """
    Serviço de ranking de usuários.

    Pontuação calculada com base em:
    - Questões respondidas: 10 pontos cada
    - Acertos: 5 pontos adicionais
    - Sequência de estudos: 2 pontos por dia
    - Consistência: bônus de 50 pontos para quem estuda 7+ dias consecutivos
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._ranking = RankingRepository(session)
        self._daily_stats = UserDailyStatRepository(session)
        self._streak = StudyStreakRepository(session)

    # ==================================================================== #
    # LEITURA
    # ==================================================================== #

    async def get_global_ranking(
        self,
        user_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[UserRanking], int | None]:
        """Retorna ranking global com a posição do usuário."""
        rankings = await self._ranking.get_global_ranking(limit=limit, offset=offset)
        user_position = await self._ranking.get_user_position(user_id)
        return rankings, user_position

    async def get_weekly_ranking(
        self,
        user_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[UserRanking], int | None]:
        """Retorna ranking semanal com a posição do usuário."""
        rankings = await self._ranking.get_weekly_ranking(limit=limit, offset=offset)
        user_ranking = await self._ranking.get_by_user(user_id)
        user_position = user_ranking.rank_weekly if user_ranking else None
        return rankings, user_position

    async def get_monthly_ranking(
        self,
        user_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[UserRanking], int | None]:
        """Retorna ranking mensal com a posição do usuário."""
        rankings = await self._ranking.get_monthly_ranking(limit=limit, offset=offset)
        user_ranking = await self._ranking.get_by_user(user_id)
        user_position = user_ranking.rank_monthly if user_ranking else None
        return rankings, user_position

    async def get_user_ranking(self, user_id: uuid.UUID) -> UserRanking | None:
        """Retorna o ranking de um usuário específico."""
        return await self._ranking.get_by_user(user_id)

    # ==================================================================== #
    # CÁLCULO DE PONTUAÇÃO
    # ==================================================================== #

    async def calculate_user_points(self, user_id: uuid.UUID) -> dict:
        """
        Calcula a pontuação de um usuário baseado em métricas de estudo.

        Fórmula:
        - 10 pontos por questão respondida
        - 5 pontos adicionais por acerto
        - 2 pontos por dia de sequência
        - Bônus de 50 pontos para streak >= 7 dias
        """
        # Buscar streak
        streak = await self._streak.get_by_user(user_id)
        today = date.today()
        month_start = date(today.year, today.month, 1)

        # Buscar estatísticas do mês atual
        daily_stats = await self._daily_stats.list_between(user_id, month_start, today)

        # Métricas
        total_questions = sum(s.questions_answered for s in daily_stats)
        total_correct = sum(s.correct_count for s in daily_stats)
        accuracy = (total_correct / total_questions * 100) if total_questions > 0 else 0
        current_streak = streak.current_streak if streak else 0

        # Pontuação base
        points = (total_questions * 10) + (total_correct * 5)

        # Bônus de sequência
        points += current_streak * 2

        # Bônus de consistência (7+ dias consecutivos)
        if current_streak >= 7:
            points += 50

        # Bônus de precisão (acima de 80%)
        if accuracy >= 80 and total_questions > 0:
            points += int(accuracy * 0.5)

        return {
            "total_points": points,
            "questions_answered": total_questions,
            "correct_answers": total_correct,
            "accuracy": round(accuracy, 1),
            "streak_days": current_streak,
        }

    async def calculate_weekly_points(self, user_id: uuid.UUID) -> int:
        """Calcula pontos da semana atual."""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        stats = await self._daily_stats.list_between(user_id, week_start, today)
        total_questions = sum(s.questions_answered for s in stats)
        total_correct = sum(s.correct_count for s in stats)

        return (total_questions * 10) + (total_correct * 5)

    async def calculate_monthly_points(self, user_id: uuid.UUID) -> int:
        """Calcula pontos do mês atual."""
        today = date.today()
        month_start = date(today.year, today.month, 1)

        stats = await self._daily_stats.list_between(user_id, month_start, today)
        total_questions = sum(s.questions_answered for s in stats)
        total_correct = sum(s.correct_count for s in stats)

        return (total_questions * 10) + (total_correct * 5)

    # ==================================================================== #
    # ATUALIZAÇÃO (Worker)
    # ==================================================================== #

    async def update_user_ranking(self, user_id: uuid.UUID) -> UserRanking:
        """Atualiza o ranking de um único usuário."""
        # Calcular pontuação
        points = await self.calculate_user_points(user_id)

        # Calcular pontos semanais e mensais
        weekly_points = await self.calculate_weekly_points(user_id)
        monthly_points = await self.calculate_monthly_points(user_id)

        # Atualizar no banco
        ranking = await self._ranking.upsert(
            user_id,
            **points,
            weekly_points=weekly_points,
            monthly_points=monthly_points,
            updated_at=datetime.now(UTC),
        )

        return ranking

    async def update_all_rankings(self) -> None:
        """
        Atualiza o ranking de todos os usuários (chamado pelo worker).

        Busca todos os usuários com atividade e recalcula suas pontuações.
        """
        from app.models.analytics.user_stats import UserDailyStat
        from sqlalchemy import select

        # Buscar todos os usuários com atividade
        stmt = select(UserDailyStat.user_id).distinct()
        result = await self._session.execute(stmt)
        user_ids = [row[0] for row in result.all()]

        # Atualizar cada usuário
        for user_id in user_ids:
            await self.update_user_ranking(user_id)

        # Recalcular posições
        await self._ranking.update_rankings()
        
        # Commit explícito
        await self._session.commit()

    async def update_ranking_by_email(self, email: str) -> UserRanking:
        """Atualiza o ranking de um usuário pelo email."""
        from app.models.identity.user import User
        from sqlalchemy import select

        result = await self._session.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError(f"Usuário com email '{email}' não encontrado")

        return await self.update_user_ranking(user.id)