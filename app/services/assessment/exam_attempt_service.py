"""Regras de negócio de execuções de simulado (`ExamAttempt`).

Reutiliza `QuestionAttempt` (practice, Etapa 8) como tabela unificada de
respostas — cada resposta de simulado também grava lá, com
`session_type=SIMULADO` e `session_id=exam_attempt.id`, exatamente como
antecipado no comentário de modelagem daquela tabela. Isso mantém o
histórico geral (`GET /attempts`) e futuras Estatísticas funcionando sem
qualquer alteração fora deste contexto.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.assessment.exam_attempt import ExamAttempt, ExamAttemptQuestion
from app.models.content.question import Question
from app.models.enums import (
    ExamAttemptStatus,
    FeatureKey,
    QuestionDifficulty,
    QuestionStatus,
    SessionType,
)
from app.models.practice.question_attempt import QuestionAttempt
from app.repositories.assessment.exam_attempt_repository import ExamAttemptRepository
from app.repositories.assessment.exam_template_repository import ExamTemplateRepository
from app.repositories.content.question_repository import QuestionFilters, QuestionRepository
from app.repositories.practice.question_attempt_repository import QuestionAttemptRepository
from app.schemas.practice.question_attempt import AnswerSubmitRequest
from app.services.billing.feature_gate_service import FeatureGateService


def _filters_from_snapshot(snapshot: dict[str, object]) -> QuestionFilters:
    """Reconstrói `QuestionFilters` a partir do `filters_snapshot` (JSONB) do molde."""

    def _uuid(key: str) -> uuid.UUID | None:
        value = snapshot.get(key)
        return uuid.UUID(str(value)) if value else None

    year_value = snapshot.get("year")
    difficulty_value = snapshot.get("difficulty")
    return QuestionFilters(
        discipline_id=_uuid("discipline_id"),
        subject_id=_uuid("subject_id"),
        topic_id=_uuid("topic_id"),
        exam_board_id=_uuid("exam_board_id"),
        exam_edition_id=_uuid("exam_edition_id"),
        organization_id=_uuid("organization_id"),
        year=int(str(year_value)) if year_value is not None else None,
        difficulty=QuestionDifficulty(str(difficulty_value)) if difficulty_value else None,
        status=QuestionStatus.PUBLICADA,
        tag_id=_uuid("tag_id"),
    )


class ExamAttemptService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._attempts = ExamAttemptRepository(session)
        self._templates = ExamTemplateRepository(session)
        self._questions = QuestionRepository(session)
        self._answers = QuestionAttemptRepository(session)
        self._feature_gate = FeatureGateService(session)

    async def start_attempt(self, user_id: uuid.UUID, exam_template_id: uuid.UUID) -> ExamAttempt:
        await self._feature_gate.assert_feature(user_id, FeatureKey.SIMULADOS)

        template = await self._templates.get_by_id(exam_template_id)
        if template is None or not (template.is_public or template.created_by == user_id):
            raise NotFoundError("Molde de simulado não encontrado.")

        # ETAPA (2026-08-15): molde criado a partir de uma seleção explícita
        # do Banco de Questões (`ExamTemplateCreateRequest.question_ids`)
        # usa exatamente essas questões, na ordem em que foram selecionadas
        # — não sorteia por filtro. Ver `exam_template_service._filters_snapshot`.
        selected_ids = template.filters_snapshot.get("question_ids")
        if selected_ids:
            ids = [uuid.UUID(str(value)) for value in selected_ids]
            by_id = {question.id: question for question in await self._questions.list_by_ids(ids)}
            questions = [by_id[qid] for qid in ids if qid in by_id]
        else:
            filters = _filters_from_snapshot(template.filters_snapshot)
            questions = await self._questions.list_random(filters, limit=template.question_count)

        if not questions:
            raise NotFoundError("Nenhuma questão encontrada para os filtros do molde.")

        now = datetime.now(UTC)
        attempt = ExamAttempt(
            exam_template_id=template.id,
            user_id=user_id,
            status=ExamAttemptStatus.EM_ANDAMENTO,
            total_questions=len(questions),
            correct_count=0,
            started_at=now,
        )
        attempt.questions = [
            ExamAttemptQuestion(question_id=question.id, position=position)
            for position, question in enumerate(questions)
        ]

        async with UnitOfWork(self._session):
            await self._attempts.add(attempt)

        return await self.get_attempt(attempt.id, user_id)

    async def get_attempt(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> ExamAttempt:
        attempt = await self._attempts.get_with_questions(attempt_id)
        # `NotFoundError` também para simulado de outro usuário — não expõe existência.
        if attempt is None or attempt.user_id != user_id:
            raise NotFoundError("Simulado não encontrado.")
        return attempt

    async def list_attempts(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[ExamAttempt]:
        return await self._attempts.list_paginated(
            user_id=user_id, limit=limit, cursor_id=cursor_id
        )

    async def get_attempt_questions(
        self, attempt: ExamAttempt
    ) -> tuple[list[Question], dict[uuid.UUID, Question]]:
        """Questões do simulado, na ordem, com as relações carregadas."""
        question_ids = [item.question_id for item in attempt.questions]
        questions = await self._questions.list_by_ids(question_ids)
        by_id = {question.id: question for question in questions}
        ordered = [by_id[qid] for qid in question_ids if qid in by_id]
        return ordered, by_id

    async def get_time_limit_minutes(self, attempt: ExamAttempt) -> int | None:
        """Tempo limite (minutos) do molde que originou o simulado, se houver."""
        template = await self._templates.get_by_id(attempt.exam_template_id)
        return template.time_limit_minutes if template is not None else None

    async def get_answered_question_ids(
        self, user_id: uuid.UUID, attempt_id: uuid.UUID
    ) -> set[uuid.UUID]:
        answers = await self._answers.list_by_session(
            user_id=user_id, session_type=SessionType.SIMULADO, session_id=attempt_id
        )
        return {answer.question_id for answer in answers}

    async def submit_answer(
        self,
        user_id: uuid.UUID,
        attempt_id: uuid.UUID,
        question_id: uuid.UUID,
        data: AnswerSubmitRequest,
    ) -> QuestionAttempt:
        attempt = await self._attempts.get_with_questions(attempt_id)
        if attempt is None or attempt.user_id != user_id:
            raise NotFoundError("Simulado não encontrado.")
        if attempt.status != ExamAttemptStatus.EM_ANDAMENTO:
            raise ConflictError("Simulado não está em andamento — não é possível responder.")

        attempt_question = next(
            (item for item in attempt.questions if item.question_id == question_id), None
        )
        if attempt_question is None:
            raise NotFoundError("Questão não pertence a este simulado.")

        already_answered = await self._answers.get_for_question_in_session(
            user_id=user_id,
            question_id=question_id,
            session_type=SessionType.SIMULADO,
            session_id=attempt_id,
        )
        if already_answered is not None:
            raise ConflictError("Questão já respondida neste simulado.")

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

        answer = QuestionAttempt(
            user_id=user_id,
            question_id=question_id,
            session_type=SessionType.SIMULADO,
            session_id=attempt_id,
            selected_alternative_id=data.selected_alternative_id,
            is_correct=is_correct,
            time_spent_seconds=data.time_spent_seconds,
        )
        answer.question = question  # evita lazy-load em `answer.question` após a sessão fechar

        async with UnitOfWork(self._session):
            await self._answers.add(answer)
            attempt_question.selected_alternative_id = data.selected_alternative_id
            attempt_question.is_correct = is_correct
            attempt_question.time_spent_seconds = data.time_spent_seconds
            self._session.add(attempt_question)
            if is_correct:
                attempt.correct_count += 1
                self._session.add(attempt)

        return answer

    async def finish_attempt(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> ExamAttempt:
        attempt = await self.get_attempt(attempt_id, user_id)
        if attempt.status != ExamAttemptStatus.EM_ANDAMENTO:
            raise ConflictError("Simulado já finalizado ou abandonado.")

        async with UnitOfWork(self._session):
            attempt.status = ExamAttemptStatus.FINALIZADO
            attempt.finished_at = datetime.now(UTC)
            self._session.add(attempt)

        return await self.get_attempt(attempt_id, user_id)

    async def abandon_attempt(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> ExamAttempt:
        attempt = await self.get_attempt(attempt_id, user_id)
        if attempt.status != ExamAttemptStatus.EM_ANDAMENTO:
            raise ConflictError("Simulado já finalizado ou abandonado.")

        async with UnitOfWork(self._session):
            attempt.status = ExamAttemptStatus.ABANDONADO
            attempt.finished_at = datetime.now(UTC)
            self._session.add(attempt)

        return await self.get_attempt(attempt_id, user_id)