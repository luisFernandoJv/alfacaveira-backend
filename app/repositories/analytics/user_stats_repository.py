"""Repositórios de acesso a dados de estatísticas pré-agregadas do aluno.

Leem exclusivamente as tabelas de agregação (`user_daily_stats`,
`user_subject_stats`, `study_streaks`) — populadas por um worker em
background a partir de `question_attempts` (ver docstring de
`app/models/analytics/user_stats.py`). Nenhum destes repositórios recalcula
nada a partir da tabela crua; se o worker ainda não rodou para um usuário,
as consultas simplesmente não retornam linhas.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.models.analytics.user_stats import StudyStreak, UserDailyStat, UserSubjectStat
from app.models.content.question import Question
from app.models.practice.question_attempt import QuestionAttempt
from app.repositories.base import BaseRepository


class UserDailyStatRepository(BaseRepository[UserDailyStat]):
    model = UserDailyStat

    async def list_between(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[UserDailyStat]:
        """Estatísticas diárias do usuário no intervalo [start_date, end_date]."""
        stmt = (
            select(UserDailyStat)
            .where(
                UserDailyStat.user_id == user_id,
                UserDailyStat.date >= start_date,
                UserDailyStat.date <= end_date,
            )
            .order_by(UserDailyStat.date.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sum_totals(self, user_id: uuid.UUID) -> dict[str, int]:
        """Soma o histórico disponível nos agregados diários do usuário."""
        stmt = select(
            func.coalesce(func.sum(UserDailyStat.questions_answered), 0),
            func.coalesce(func.sum(UserDailyStat.correct_count), 0),
            func.coalesce(func.sum(UserDailyStat.time_studied_seconds), 0),
        ).where(UserDailyStat.user_id == user_id)
        row = (await self.session.execute(stmt)).one()
        return {
            "questions_answered": int(row[0]),
            "correct_count": int(row[1]),
            "time_studied_seconds": int(row[2]),
        }

    async def get_for_date(self, user_id: uuid.UUID, target_date: date) -> UserDailyStat | None:
        stmt = select(UserDailyStat).where(
            UserDailyStat.user_id == user_id, UserDailyStat.date == target_date
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class UserSubjectStatRepository(BaseRepository[UserSubjectStat]):
    model = UserSubjectStat

    async def list_by_user(self, user_id: uuid.UUID) -> list[UserSubjectStat]:
        """Estatísticas por disciplina do usuário, com a disciplina já carregada."""
        stmt = (
            select(UserSubjectStat)
            .where(UserSubjectStat.user_id == user_id)
            .options(selectinload(UserSubjectStat.discipline))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())


class StudyStreakRepository(BaseRepository[StudyStreak]):
    model = StudyStreak

    async def get_by_user(self, user_id: uuid.UUID) -> StudyStreak | None:
        # `StudyStreak` não tem coluna `id` — a PK é `user_id` — então não dá
        # para usar `BaseRepository.get_by_id` aqui; `session.get` aceita a
        # PK diretamente.
        return await self.session.get(StudyStreak, user_id)