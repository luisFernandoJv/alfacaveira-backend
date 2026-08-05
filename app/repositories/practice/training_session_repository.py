"""Repositório de acesso a dados de `TrainingSession`.

Listagem paginada por keyset (`created_at, id`), sempre restrita ao dono da
sessão — treino é um recurso pessoal, nunca listado entre usuários.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.practice.training_session import TrainingSession
from app.repositories.base import BaseRepository

_RELATIONS = (selectinload(TrainingSession.questions),)


class TrainingSessionRepository(BaseRepository[TrainingSession]):
    model = TrainingSession

    async def get_with_questions(self, session_id: uuid.UUID) -> TrainingSession | None:
        stmt = (
            select(TrainingSession)
            .where(TrainingSession.id == session_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[TrainingSession]:
        """Histórico de sessões do usuário, mais recentes primeiro."""
        stmt = (
            select(TrainingSession)
            .where(TrainingSession.user_id == user_id)
            .order_by(TrainingSession.created_at.desc(), TrainingSession.id.desc())
            .limit(limit)
        )

        if cursor_id is not None:
            cursor_session = await self.get_by_id(cursor_id)
            if cursor_session is not None:
                stmt = stmt.where(
                    (TrainingSession.created_at < cursor_session.created_at)
                    | (
                        (TrainingSession.created_at == cursor_session.created_at)
                        & (TrainingSession.id < cursor_session.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())
