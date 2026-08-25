# app/services/practice/training_session_service.py
import uuid
from datetime import UTC, datetime
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationDomainError
from app.database.uow import UnitOfWork
from app.models.content.question import Question
from app.models.enums import FeatureKey, QuestionAnswerStatus, QuestionStatus, SessionType
from app.models.practice.question_attempt import QuestionAttempt
from app.models.practice.training_session import TrainingSession, TrainingSessionQuestion
from app.repositories.content.question_repository import QuestionFilters, QuestionRepository
from app.repositories.practice.question_attempt_repository import QuestionAttemptRepository
from app.repositories.practice.training_session_repository import TrainingSessionRepository
from app.repositories.learning.notebook_repository import NotebookRepository
from app.repositories.learning.notebook_question_repository import NotebookQuestionRepository
from app.schemas.practice.training_session import TrainingSessionCreateRequest
from app.services.billing.feature_gate_service import FeatureGateService

logger = structlog.get_logger(__name__)


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
        "exclude_answered": data.exclude_answered,
    }


class TrainingSessionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._questions = QuestionRepository(session)
        self._attempts = QuestionAttemptRepository(session)
        self._notebooks = NotebookRepository(session)
        self._notebook_questions = NotebookQuestionRepository(session)
        self._feature_gate = FeatureGateService(session)

    async def create_session(
        self, user_id: uuid.UUID, data: TrainingSessionCreateRequest
    ) -> TrainingSession:
        """Cria uma sessão de treino a partir de filtros, lista explícita ou caderno."""
        logger.info(
            "training_session.create.start",
            user_id=str(user_id),
            has_notebook_id=bool(data.notebook_id),
            has_question_ids=bool(data.question_ids),
        )

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
            # Sem `user_id`, `_apply_filters` ignora `answer_status` (ver
            # `QuestionRepository._apply_filters`) — precisa dos dois juntos
            # pra "só questões que eu ainda não respondi" funcionar.
            answer_status=QuestionAnswerStatus.NAO_RESPONDIDA if data.exclude_answered else None,
            user_id=user_id if data.exclude_answered else None,
        )
        questions = await self._questions.list_random(filters, limit=data.quantity)
        if not questions and data.exclude_answered:
            # Sem isso, "acabaram as questões novas" vira o mesmo erro genérico
            # de "nenhuma questão encontrada para os filtros", que leva o
            # aluno a mexer nos filtros errados achando que é isso.
            raise NotFoundError(
                "Você já respondeu todas as questões que batem com esses filtros. "
                "Desmarque \"somente questões novas\" para revisar as que já respondeu."
            )
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
        logger.info("notebook_session.start", notebook_id=str(notebook_id), user_id=str(user_id))

        # Verificar ownership do caderno
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        # Buscar questões do caderno
        notebook_questions, _ = await self._notebook_questions.list_by_notebook(
            notebook_id=notebook_id,
            user_id=user_id,
            limit=1000,  # Limite alto para não truncar
        )

        logger.info(
            "notebook_session.questions_found",
            notebook_id=str(notebook_id),
            count=len(notebook_questions),
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
        data: TrainingSessionCreateRequest,
    ) -> TrainingSession:
        """Persiste a sessão no banco de dados."""
        logger.info(
            "session.persist.start",
            user_id=str(user_id),
            question_count=len(questions),
        )

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
            logger.info("session.persist.committed", session_id=str(training_session.id))

        return await self.get_session(training_session.id, user_id)

    async def get_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> TrainingSession:
        training_session = await self._sessions.get_with_questions(session_id)
        if training_session is None or training_session.user_id != user_id:
            raise NotFoundError("Sessão de treino não encontrada.")
        return training_session

    async def list_sessions(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> tuple[list[TrainingSession], bool]:
        """Mesma correção de `QuestionAttemptService.list_history`: busca
        `limit + 1` e descarta o extra para saber com certeza se há próxima
        página, em vez de inferir errado quando o total é múltiplo exato de
        `limit`."""
        sessions = await self._sessions.list_paginated(
            user_id=user_id, limit=limit + 1, cursor_id=cursor_id
        )
        has_more = len(sessions) > limit
        return sessions[:limit], has_more

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

    async def get_session_attempts_by_question(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> dict[uuid.UUID, QuestionAttempt]:
        """Tentativa por questão nesta sessão — usado para reconstruir o
        resultado (alternativa marcada, acerto/erro) de questões já
        respondidas ao retomar a sessão (`GET .../training-sessions/{id}`).
        Sem isso, o frontend perde a resposta ao sair e voltar: o `answered`
        booleano sozinho não basta para remontar o `AnswerRecord`.
        """
        attempts = await self._attempts.list_by_session(
            user_id=user_id, session_type=SessionType.TREINO, session_id=session_id
        )
        # Em teoria há no máximo 1 attempt por (user, questão, sessão) — o
        # `ConflictError` em `submit_training_answer` impede um segundo. Usa
        # dict simples (última tentativa vence) para não quebrar se algum
        # dado legado tiver duplicata.
        return {attempt.question_id: attempt for attempt in attempts}

    async def update_position(
        self, session_id: uuid.UUID, user_id: uuid.UUID, current_question_index: int
    ) -> TrainingSession:
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