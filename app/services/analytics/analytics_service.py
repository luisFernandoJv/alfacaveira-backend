"""Regras de negócio de estatísticas agregadas do aluno (analytics).

Este service não deriva nenhum número a partir de `question_attempts` — ele
apenas lê os agregados já calculados pelo worker de background em `app/workers/analytics_aggregator.py`.
Enquanto o worker ainda não tiver produzido dados para um usuário, os métodos
abaixo devolvem listas vazias / valores zerados, nunca dados fictícios: é papel
da camada HTTP decidir como representar "sem dado ainda" para o frontend.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics.user_stats import StudyStreak, UserDailyStat, UserSubjectStat
from app.repositories.analytics.user_stats_repository import (
    StudyStreakRepository,
    UserDailyStatRepository,
    UserSubjectStatRepository,
)


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._daily = UserDailyStatRepository(session)
        self._subject = UserSubjectStatRepository(session)
        self._streak = StudyStreakRepository(session)

    async def get_daily_stats(self, user_id: uuid.UUID, days: int) -> list[UserDailyStat]:
        """Estatísticas diárias dos últimos `days` dias (incluindo hoje).

        Dias sem nenhuma atividade não geram linha em `user_daily_stats` —
        a lista pode vir mais curta que `days`; cabe ao consumidor decidir
        se quer preencher os buracos com zero.
        """
        today = self._today()
        start = today - timedelta(days=days - 1)
        return await self._daily.list_between(user_id, start, today)

    async def get_today_stat(self, user_id: uuid.UUID) -> UserDailyStat | None:
        return await self._daily.get_for_date(user_id, self._today())

    async def get_subject_performance(self, user_id: uuid.UUID) -> list[UserSubjectStat]:
        return await self._subject.list_by_user(user_id)

    async def get_streak(self, user_id: uuid.UUID) -> StudyStreak | None:
        return await self._streak.get_by_user(user_id)

    async def get_lifetime_totals(self, user_id: uuid.UUID) -> dict[str, int]:
        """Totais históricos já agregados em `user_daily_stats`."""
        return await self._daily.sum_totals(user_id)

    async def get_subject_trends(
        self, user_id: uuid.UUID, *, days: int = 30
    ) -> list[dict[str, object]]:
        """Compara o aproveitamento por disciplina em duas janelas recentes.

        A tendência é derivada da fonte de verdade (`question_attempts`) apenas
        para a comparação temporal; os totais consolidados continuam vindo dos
        agregados. Disciplinas com volume insuficiente em uma das janelas não
        recebem uma tendência artificial.
        """
        return await self._subject.list_trends(user_id, days=days)

    @staticmethod
    def calculate_performance_score(
        *,
        accuracy: float,
        active_days: int,
        streak: int,
    ) -> int | None:
        """Score 0-100 derivado somente de métricas reais dos últimos 30 dias.

        Pesos são regras de apresentação, não dados fictícios:
        60% aproveitamento + 25% consistência + 15% sequência.
        """
        if accuracy <= 0 and active_days <= 0 and streak <= 0:
            return None
        accuracy_component = max(0.0, min(accuracy, 100.0)) * 0.60
        consistency_component = min(active_days / 30.0, 1.0) * 100.0 * 0.25
        streak_component = min(streak / 30.0, 1.0) * 100.0 * 0.15
        return round(accuracy_component + consistency_component + streak_component)

    @staticmethod
    def _today() -> date:
        return datetime.now(UTC).date()