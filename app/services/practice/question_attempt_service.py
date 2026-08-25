"""Regras de negócio de tentativas de resposta (`QuestionAttempt`).

Submeter uma resposta é sempre relativo a uma sessão existente (hoje, só
`treino`; `simulado` reutilizará esta mesma tabela na Etapa 9 —
`assessment`). Cada resposta atualiza o contador `correct_count` da sessão
de forma atômica, junto com o registro de `QuestionAttempt`.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.enums import SessionType
from app.models.practice.question_attempt import QuestionAttempt
from app.repositories.content.question_repository import QuestionRepository
from app.repositories.practice.question_attempt_repository import QuestionAttemptRepository
from app.repositories.practice.training_session_repository import TrainingSessionRepository
from app.schemas.practice.question_attempt import AnswerSubmitRequest


class QuestionAttemptService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._attempts = QuestionAttemptRepository(session)
        self._questions = QuestionRepository(session)
        self._sessions = TrainingSessionRepository(session)

    async def submit_training_answer(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        data: AnswerSubmitRequest,
    ) -> QuestionAttempt:
        training_session = await self._sessions.get_with_questions(session_id)
        if training_session is None or training_session.user_id != user_id:
            raise NotFoundError("Sessão de treino não encontrada.")
        if training_session.finished_at is not None:
            raise ConflictError("Sessão já finalizada — não é possível responder.")
        if not any(item.question_id == question_id for item in training_session.questions):
            raise NotFoundError("Questão não pertence a esta sessão de treino.")

        already_answered = await self._attempts.get_for_question_in_session(
            user_id=user_id,
            question_id=question_id,
            session_type=SessionType.TREINO,
            session_id=session_id,
        )
        if already_answered is not None:
            raise ConflictError("Questão já respondida nesta sessão.")

        question = await self._questions.get_with_relations(question_id)
        if question is None:
            raise NotFoundError("Questão não encontrada.")

        selected_letter = None
        if data.selected_alternative_id is not None:
            selected = next(
                (alt for alt in question.alternatives if alt.id == data.selected_alternative_id),
                None,
            )
            if selected is None:
                raise NotFoundError("Alternativa não encontrada para esta questão.")
            selected_letter = selected.letter

        is_correct = selected_letter == question.correct_alternative_letter

        attempt = QuestionAttempt(
            user_id=user_id,
            question_id=question_id,
            session_type=SessionType.TREINO,
            session_id=session_id,
            selected_alternative_id=data.selected_alternative_id,
            is_correct=is_correct,
            time_spent_seconds=data.time_spent_seconds,
        )
        attempt.question = question  # evita lazy-load em `attempt.question` após a sessão fechar

        async with UnitOfWork(self._session):
            await self._attempts.add(attempt)
            if is_correct:
                training_session.correct_count += 1
                self._session.add(training_session)

        return attempt

    async def list_history(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> tuple[list[QuestionAttempt], bool]:
        """Uma página do histórico + se existe página seguinte.

        Busca `limit + 1` registros e descarta o extra: com `limit` exatos,
        `len(attempts) == limit` não diz se acabou a lista ou se ela termina
        bem ali — as duas situações ficam indistinguíveis, e o cliente acaba
        disparando um `loadMore` a mais que sempre volta vazio quando o
        total é múltiplo exato de `limit`. O item extra resolve a ambiguidade
        sem precisar de `COUNT(*)` (caro em tabela de alto volume).
        """
        attempts = await self._attempts.list_paginated(
            user_id=user_id, limit=limit + 1, cursor_id=cursor_id
        )
        has_more = len(attempts) > limit
        return attempts[:limit], has_more