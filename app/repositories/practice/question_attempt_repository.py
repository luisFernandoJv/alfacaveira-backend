"""Repositório de acesso a dados de `QuestionAttempt` (histórico de respostas)."""

import uuid
from datetime import datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.enums import SessionType
from app.models.practice.question_attempt import QuestionAttempt
from app.repositories.base import BaseRepository

_RELATIONS = (selectinload(QuestionAttempt.question),)


class QuestionAttemptRepository(BaseRepository[QuestionAttempt]):
    model = QuestionAttempt

    async def get_for_question_in_session(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
        session_type: SessionType,
        session_id: uuid.UUID,
    ) -> QuestionAttempt | None:
        """Tentativa já registrada para esta questão dentro desta sessão, se houver."""
        stmt = select(QuestionAttempt).where(
            QuestionAttempt.user_id == user_id,
            QuestionAttempt.question_id == question_id,
            QuestionAttempt.session_type == session_type,
            QuestionAttempt.session_id == session_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_answered_today(
        self, user_id: uuid.UUID, session_type: SessionType
    ) -> int:
        """Quantidade de respostas do usuário hoje (UTC) para uma origem
        (`session_type`). Usado pelo Feature Gate de quota `daily_questions`
        — não conta respostas de outras origens (ex.: simulado tem seu
        próprio gate, `simulados`, e não compartilha a cota diária)."""
        today_start = datetime.combine(
            datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
        )
        stmt = select(func.count()).select_from(QuestionAttempt).where(
            QuestionAttempt.user_id == user_id,
            QuestionAttempt.session_type == session_type,
            QuestionAttempt.answered_at >= today_start,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_by_session(
        self, user_id: uuid.UUID, session_type: SessionType, session_id: uuid.UUID
    ) -> list[QuestionAttempt]:
        stmt = select(QuestionAttempt).where(
            QuestionAttempt.user_id == user_id,
            QuestionAttempt.session_type == session_type,
            QuestionAttempt.session_id == session_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_paginated(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[QuestionAttempt]:
        """Histórico de respostas do usuário (qualquer origem), mais recentes primeiro."""
        stmt = (
            select(QuestionAttempt)
            .where(QuestionAttempt.user_id == user_id)
            .options(*_RELATIONS)
            .order_by(QuestionAttempt.answered_at.desc(), QuestionAttempt.id.desc())
            .limit(limit)
        )

        if cursor_id is not None:
            cursor_attempt = await self.get_by_id(cursor_id)
            if cursor_attempt is not None:
                stmt = stmt.where(
                    (QuestionAttempt.answered_at < cursor_attempt.answered_at)
                    | (
                        (QuestionAttempt.answered_at == cursor_attempt.answered_at)
                        & (QuestionAttempt.id < cursor_attempt.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())