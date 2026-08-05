"""Repositório de acesso a dados de `ExamAttempt`.

Listagem paginada por keyset (`created_at, id`), sempre restrita ao dono do
simulado — mesmo padrão de `TrainingSessionRepository` (Etapa 8): simulado
respondido é um recurso pessoal, nunca listado entre usuários.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.assessment.exam_attempt import ExamAttempt
from app.repositories.base import BaseRepository

_RELATIONS = (selectinload(ExamAttempt.questions),)


class ExamAttemptRepository(BaseRepository[ExamAttempt]):
    model = ExamAttempt

    async def get_with_questions(self, attempt_id: uuid.UUID) -> ExamAttempt | None:
        stmt = select(ExamAttempt).where(ExamAttempt.id == attempt_id).options(*_RELATIONS)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[ExamAttempt]:
        """Histórico de simulados do usuário, mais recentes primeiro."""
        stmt = (
            select(ExamAttempt)
            .where(ExamAttempt.user_id == user_id)
            .order_by(ExamAttempt.created_at.desc(), ExamAttempt.id.desc())
            .limit(limit)
        )

        if cursor_id is not None:
            cursor_attempt = await self.get_by_id(cursor_id)
            if cursor_attempt is not None:
                stmt = stmt.where(
                    (ExamAttempt.created_at < cursor_attempt.created_at)
                    | (
                        (ExamAttempt.created_at == cursor_attempt.created_at)
                        & (ExamAttempt.id < cursor_attempt.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())
