"""Repositórios de acesso a dados de estatísticas pré-agregadas do aluno.

Leem exclusivamente as tabelas de agregação (`user_daily_stats`,
`user_subject_stats`, `study_streaks`) — populadas por um worker em
background a partir de `question_attempts` (ver docstring de
`app/models/analytics/user_stats.py`). Nenhum destes repositórios recalcula
nada a partir da tabela crua; se o worker ainda não rodou para um usuário,
as consultas simplesmente não retornam linhas.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.analytics.user_stats import StudyStreak, UserDailyStat, UserSubjectStat
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

    async def get_for_date(self, user_id: uuid.UUID, target_date: date) -> UserDailyStat | None:
        stmt = select(UserDailyStat).where(
            UserDailyStat.user_id == user_id, UserDailyStat.date == target_date
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def sum_window(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> tuple[int, int, int, int]:
        """Agregado SQL (SUM) de `user_daily_stats` no intervalo [start_date, end_date].

        Retorna (questions_answered, correct_count, time_studied_seconds,
        active_days) -- active_days e a contagem de linhas no intervalo (dias
        com pelo menos uma resposta), usada no componente de "regularidade"
        do Performance Score. Feito em SQL (nao em Python sobre
        list_between) porque e um agregado, nao uma listagem.
        """
        stmt = select(
            func.coalesce(func.sum(UserDailyStat.questions_answered), 0),
            func.coalesce(func.sum(UserDailyStat.correct_count), 0),
            func.coalesce(func.sum(UserDailyStat.time_studied_seconds), 0),
            func.count(UserDailyStat.id),
        ).where(
            UserDailyStat.user_id == user_id,
            UserDailyStat.date >= start_date,
            UserDailyStat.date <= end_date,
        )
        result = await self.session.execute(stmt)
        row = result.one()
        return int(row[0]), int(row[1]), int(row[2]), int(row[3])

    async def sum_lifetime(self, user_id: uuid.UUID) -> tuple[int, int, int]:
        """Totais vitalicios reais do usuario -- SUM sobre toda a historia de
        `user_daily_stats` (nao apenas a janela filtrada pela tela).

        Retorna (questions_answered, correct_count, time_studied_seconds).
        """
        stmt = select(
            func.coalesce(func.sum(UserDailyStat.questions_answered), 0),
            func.coalesce(func.sum(UserDailyStat.correct_count), 0),
            func.coalesce(func.sum(UserDailyStat.time_studied_seconds), 0),
        ).where(UserDailyStat.user_id == user_id)
        result = await self.session.execute(stmt)
        row = result.one()
        return int(row[0]), int(row[1]), int(row[2])


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