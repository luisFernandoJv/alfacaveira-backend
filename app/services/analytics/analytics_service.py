"""Regras de negócio de estatísticas agregadas do aluno (analytics).

Este service não deriva nenhum número a partir de `question_attempts` — ele
apenas lê os agregados já calculados pelo worker de background (que ainda
não existe, ver `app/workers`, vazio). Enquanto o worker não roda, os
métodos abaixo devolvem listas vazias / valores zerados, nunca dados
fictícios: é papel da camada HTTP (router) decidir como representar "sem
dado ainda" para o frontend.
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

    @staticmethod
    def _today() -> date:
        return datetime.now(UTC).date()
