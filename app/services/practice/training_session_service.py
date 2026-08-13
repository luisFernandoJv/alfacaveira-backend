"""Regras de negócio de sessões de treino: criação a partir de filtros,
consulta (histórico + detalhe) e finalização.
"""

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationDomainError
from app.database.uow import UnitOfWork
from app.models.content.question import Question
from app.models.enums import FeatureKey, QuestionStatus, SessionType
from app.models.practice.training_session import TrainingSession, TrainingSessionQuestion
from app.repositories.content.question_repository import QuestionFilters, QuestionRepository
from app.repositories.practice.question_attempt_repository import QuestionAttemptRepository
from app.repositories.practice.training_session_repository import TrainingSessionRepository
from app.repositories.learning.notebook_repository import NotebookRepository
from app.schemas.practice.training_session import TrainingSessionCreateRequest
from app.services.billing.feature_gate_service import FeatureGateService


def _filters_snapshot(data: TrainingSessionCreateRequest) -> dict[str, object]:
    """Snapshot (JSONB) dos filtros usados para montar a sessão."""
    return {
        "discipline_id": str(data.discipline_id) if data.discipline_id else None,
        "subject_id": str(data.subject_id) if data.subject_id else None,
        "topic_id": str(data.topic_id) if data.topic_id else None,
        "exam_board_id": str(data.exam_board_id) if data.exam_board_id else None,
        "exam_edition_id": str(data.exam_edition_id) if data.exam_edition_id else None,
        "organization_id": str(data.organization_id) if data.organization_id else None,
        "year": data.year,
        "difficulty": data.difficulty.value if data.difficulty else None,
        "tag_id": str(data.tag_id) if data.tag_id else None,
        "quantity": data.quantity,
        "question_ids": [str(qid) for qid in (data.question_ids or [])],
        "notebook_id": str(data.notebook_id) if data.notebook_id else None,
    }


class TrainingSessionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._questions = QuestionRepository(session)
        self._attempts = QuestionAttemptRepository(session)
        self._notebooks = NotebookRepository(session)
        self._feature_gate = FeatureGateService(session)

    async def create_session(
        self, user_id: uuid.UUID, data: TrainingSessionCreateRequest
    ) -> TrainingSession:
        """Cria uma sessão de treino a partir de filtros ou de uma lista explícita de questões."""
        
        # Se for criar a partir de um caderno, usa as questões do caderno
        if data.notebook_id:
            return await self._create_session_from_notebook(user_id, data.notebook_id, data)
        
        # Se for criar a partir de uma lista explícita de IDs
        if data.question_ids:
            return await self._create_session_from_question_ids(user_id, data.question_ids, data)
        
        # Caso contrário, usa os filtros tradicionais
        return await self._create_session_from_filters(user_id, data)

    async def _create_session_from_filters(
        self, user_id: uuid.UUID, data: TrainingSessionCreateRequest
    ) -> TrainingSession:
        """Cria sessão a partir de filtros (comportamento original)."""
        answered_today = await self._attempts.count_answered_today(
            user_id, session_type=SessionType.TREINO
        )
        await self._feature_gate.assert_within_quota(
            user_id, FeatureKey.DAILY_QUESTIONS, answered_today
        )

        filters = QuestionFilters(
            discipline_id=data.discipline_id,
            subject_id=data.subject_id,
            topic_id=data.topic_id,
            exam_board_id=data.exam_board_id,
            exam_edition_id=data.exam_edition_id,
            organization_id=data.organization_id,
            year=data.year,
            difficulty=data.difficulty,
            status=QuestionStatus.PUBLICADA,
            tag_id=data.tag_id,
        )
        questions = await self._questions.list_random(filters, limit=data.quantity)
        if not questions:
            raise NotFoundError("Nenhuma questão encontrada para os filtros informados.")

        return await self._persist_session(user_id, questions, data)

    async def _create_session_from_question_ids(
        self, user_id: uuid.UUID, question_ids: list[uuid.UUID], data: TrainingSessionCreateRequest
    ) -> TrainingSession:
        """Cria sessão a partir de uma lista explícita de IDs de questões."""
        answered_today = await self._attempts.count_answered_today(
            user_id, session_type=SessionType.TREINO
        )
        await self._feature_gate.assert_within_quota(
            user_id, FeatureKey.DAILY_QUESTIONS, answered_today
        )

        # Buscar as questões pelos IDs
        questions = await self._questions.list_by_ids(question_ids)
        
        # Verificar se todas as questões foram encontradas
        found_ids = {q.id for q in questions}
        missing = [str(qid) for qid in question_ids if qid not in found_ids]
        if missing:
            raise NotFoundError(f"Questões não encontradas: {', '.join(missing[:5])}")

        return await self._persist_session(user_id, questions, data)

    async def _create_session_from_notebook(
        self, user_id: uuid.UUID, notebook_id: uuid.UUID, data: TrainingSessionCreateRequest
    ) -> TrainingSession:
        """Cria sessão a partir de um caderno específico."""
        # Verificar ownership do caderno
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        # Buscar questões do caderno
        notebook_questions, _ = await self._notebooks._questions.list_by_notebook(
            notebook_id=notebook_id,
            user_id=user_id,
            limit=1000,  # Limite alto para não truncar
        )
        
        if not notebook_questions:
            raise NotFoundError("Este caderno não possui questões para estudar.")

        # Extrair os IDs das questões
        question_ids = [nq.question_id for nq in notebook_questions]
        
        # Buscar as questões completas
        questions = await self._questions.list_by_ids(question_ids)
        
        # Verificar quota
        answered_today = await self._attempts.count_answered_today(
            user_id, session_type=SessionType.TREINO
        )
        await self._feature_gate.assert_within_quota(
            user_id, FeatureKey.DAILY_QUESTIONS, answered_today
        )

        # Criar uma cópia do data para não modificar o original
        session_data = data.model_copy()
        session_data.quantity = len(questions)
        
        return await self._persist_session(user_id, questions, session_data)

    async def _persist_session(
        self, 
        user_id: uuid.UUID, 
        questions: list[Question], 
        data: TrainingSessionCreateRequest
    ) -> TrainingSession:
        """Persiste a sessão no banco de dados."""
        now = datetime.now(UTC)
        
        # Limitar quantidade
        quantity = min(data.quantity, len(questions))
        selected_questions = questions[:quantity]
        
        training_session = TrainingSession(
            user_id=user_id,
            filters_snapshot=_filters_snapshot(data),
            total_questions=len(selected_questions),
            correct_count=0,
            started_at=now,
        )
        training_session.questions = [
            TrainingSessionQuestion(question_id=question.id, position=position)
            for position, question in enumerate(selected_questions)
        ]

        async with UnitOfWork(self._session):
            await self._sessions.add(training_session)

        return await self.get_session(training_session.id, user_id)

    async def get_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> TrainingSession:
        training_session = await self._sessions.get_with_questions(session_id)
        # `NotFoundError` também para sessão de outro usuário — não expõe existência.
        if training_session is None or training_session.user_id != user_id:
            raise NotFoundError("Sessão de treino não encontrada.")
        return training_session

    async def list_sessions(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[TrainingSession]:
        return await self._sessions.list_paginated(
            user_id=user_id, limit=limit, cursor_id=cursor_id
        )

    async def get_session_questions(
        self, training_session: TrainingSession
    ) -> tuple[list[Question], dict[uuid.UUID, Question]]:
        """Questões da sessão, na ordem, com as relações carregadas."""
        question_ids = [item.question_id for item in training_session.questions]
        questions = await self._questions.list_by_ids(question_ids)
        by_id = {question.id: question for question in questions}
        ordered = [by_id[qid] for qid in question_ids if qid in by_id]
        return ordered, by_id

    async def get_answered_question_ids(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> set[uuid.UUID]:
        attempts = await self._attempts.list_by_session(
            user_id=user_id, session_type=SessionType.TREINO, session_id=session_id
        )
        return {attempt.question_id for attempt in attempts}

    async def update_position(
        self, session_id: uuid.UUID, user_id: uuid.UUID, current_question_index: int
    ) -> TrainingSession:
        """Atualiza a posição (índice da questão) que o aluno está vendo.

        `get_session` já garante que a sessão pertence a `user_id` (levanta
        `NotFoundError` — nunca `ForbiddenError` — para não revelar a
        existência de sessões de outros usuários, mesmo padrão do resto do
        service). Nunca confia em nada além do `user_id` resolvido via
        `CurrentUser` no endpoint.
        """
        training_session = await self.get_session(session_id, user_id)
        if current_question_index >= training_session.total_questions:
            raise ValidationDomainError(
                "Posição fora do intervalo de questões da sessão."
            )

        async with UnitOfWork(self._session):
            training_session.current_question_index = current_question_index
            await self._session.flush()

        return training_session

    async def finish_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> TrainingSession:
        training_session = await self.get_session(session_id, user_id)
        if training_session.finished_at is not None:
            raise ConflictError("Sessão já finalizada.")

        async with UnitOfWork(self._session):
            training_session.finished_at = datetime.now(UTC)
            await self._session.flush()

        return await self.get_session(session_id, user_id)