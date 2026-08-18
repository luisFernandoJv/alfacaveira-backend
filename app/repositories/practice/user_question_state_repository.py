"""Repositório de acesso a dados de `UserQuestionState`."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.practice.user_question_state import UserQuestionState
from app.repositories.base import BaseRepository


class UserQuestionStateRepository(BaseRepository[UserQuestionState]):
    model = UserQuestionState

    async def get_for_question(
        self, user_id: uuid.UUID, question_id: uuid.UUID
    ) -> UserQuestionState | None:
        """Retorna o estado do usuário para a questão, ou None se ainda não existe."""
        stmt = select(UserQuestionState).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id == question_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, user_id: uuid.UUID, question_id: uuid.UUID, **fields) -> UserQuestionState:
        """Cria ou atualiza o registro de estado para o par (user, question).

        Usa INSERT … ON CONFLICT DO UPDATE para garantir atomicidade sem
        precisar de SELECT + INSERT separados. Retorna o registro atualizado.
        """
        values = {"user_id": user_id, "question_id": question_id, **fields}
        stmt = (
            insert(UserQuestionState)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_user_question_state",
                set_={k: v for k, v in fields.items()},
            )
            .returning(UserQuestionState)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def get_favorited_ids(
        self, user_id: uuid.UUID, question_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Subconjunto de `question_ids` que o usuário marcou como favorito.

        ETAPA 3 (sessão 6): usado por `QuestionService.list_questions` para
        preencher `is_favorite` na listagem, numa única query em lote (evita
        N+1 — mesmo padrão de `QuestionRepository.list_by_ids`).
        """
        if not question_ids:
            return set()
        stmt = select(UserQuestionState.question_id).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id.in_(question_ids),
            UserQuestionState.is_favorite.is_(True),
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def list_favorites(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[UserQuestionState]:
        """Questões favoritadas pelo usuário, ordenadas pelas mais recentes."""
        stmt = (
            select(UserQuestionState)
            .where(
                UserQuestionState.user_id == user_id,
                UserQuestionState.is_favorite.is_(True),
            )
            .order_by(UserQuestionState.updated_at.desc(), UserQuestionState.id.desc())
            .limit(limit)
        )
        if cursor_id is not None:
            cursor = await self.get_by_id(cursor_id)
            if cursor is not None:
                stmt = stmt.where(
                    (UserQuestionState.updated_at < cursor.updated_at)
                    | (
                        (UserQuestionState.updated_at == cursor.updated_at)
                        & (UserQuestionState.id < cursor.id)
                    )
                )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_noted(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[UserQuestionState]:
        """Questões com anotação pessoal, ordenadas pelas mais recentemente anotadas."""
        stmt = (
            select(UserQuestionState)
            .where(
                UserQuestionState.user_id == user_id,
                UserQuestionState.personal_note.isnot(None),
            )
            .order_by(UserQuestionState.noted_at.desc(), UserQuestionState.id.desc())
            .limit(limit)
        )
        if cursor_id is not None:
            cursor = await self.get_by_id(cursor_id)
            if cursor is not None:
                stmt = stmt.where(
                    (UserQuestionState.noted_at < cursor.noted_at)
                    | (
                        (UserQuestionState.noted_at == cursor.noted_at)
                        & (UserQuestionState.id < cursor.id)
                    )
                )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())