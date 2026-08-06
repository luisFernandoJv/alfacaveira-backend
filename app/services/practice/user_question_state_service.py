"""Regras de negócio de estado do usuário por questão (favorito + anotação)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database.uow import UnitOfWork
from app.models.practice.user_question_state import UserQuestionState
from app.repositories.content.question_repository import QuestionRepository
from app.repositories.practice.user_question_state_repository import UserQuestionStateRepository
from app.schemas.practice.user_question_state import FavoriteToggleRequest, NoteUpsertRequest


class UserQuestionStateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._states = UserQuestionStateRepository(session)
        self._questions = QuestionRepository(session)

    # ------------------------------------------------------------------ #
    # Leitura                                                               #
    # ------------------------------------------------------------------ #

    async def get_state(
        self, user_id: uuid.UUID, question_id: uuid.UUID
    ) -> UserQuestionState | None:
        """Retorna o estado atual ou None se o usuário nunca interagiu com a questão."""
        await self._assert_question_exists(question_id)
        return await self._states.get_for_question(user_id, question_id)

    async def list_favorites(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[UserQuestionState]:
        return await self._states.list_favorites(user_id, limit=limit, cursor_id=cursor_id)

    async def list_noted(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[UserQuestionState]:
        return await self._states.list_noted(user_id, limit=limit, cursor_id=cursor_id)

    # ------------------------------------------------------------------ #
    # Mutações                                                             #
    # ------------------------------------------------------------------ #

    async def toggle_favorite(
        self, user_id: uuid.UUID, question_id: uuid.UUID, data: FavoriteToggleRequest
    ) -> UserQuestionState:
        """Define is_favorite para o valor informado (idempotente)."""
        await self._assert_question_exists(question_id)
        async with UnitOfWork(self._session):
            state = await self._states.upsert(
                user_id=user_id,
                question_id=question_id,
                is_favorite=data.is_favorite,
            )
        return state

    async def upsert_note(
        self, user_id: uuid.UUID, question_id: uuid.UUID, data: NoteUpsertRequest
    ) -> UserQuestionState:
        """Salva ou apaga a anotação pessoal.

        String vazia é tratada como deleção — persiste NULL.
        """
        await self._assert_question_exists(question_id)
        note = data.note.strip() or None
        noted_at = datetime.now(UTC) if note is not None else None
        async with UnitOfWork(self._session):
            state = await self._states.upsert(
                user_id=user_id,
                question_id=question_id,
                personal_note=note,
                noted_at=noted_at,
            )
        return state

    # ------------------------------------------------------------------ #
    # Helpers privados                                                     #
    # ------------------------------------------------------------------ #

    async def _assert_question_exists(self, question_id: uuid.UUID) -> None:
        question = await self._questions.get_by_id(question_id)
        if question is None:
            raise NotFoundError("Questão não encontrada.")