"""Endpoints HTTP de execuções de simulado (`ExamAttempt`).

Todos os endpoints são pessoais (o próprio usuário autenticado) — mesmo
padrão de `practice/training_sessions.py` (Etapa 8). Submissão de resposta
reutiliza `AnswerSubmitRequest`/`AnswerResultResponse` de
`app.schemas.practice.question_attempt`, já que ambos os fluxos escrevem na
mesma tabela `QuestionAttempt`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.models.assessment.exam_attempt import ExamAttempt
from app.models.enums import FeatureKey
from app.schemas.assessment.exam_attempt import (
    ExamAttemptDetailResponse,
    ExamAttemptListItem,
    ExamAttemptQuestionResponse,
    ExamAttemptStartRequest,
)
from app.schemas.practice.question_attempt import AnswerResultResponse, AnswerSubmitRequest
from app.security.dependencies import CurrentUser, RequireFeature
from app.services.assessment.exam_attempt_service import ExamAttemptService

router = APIRouter()


def get_exam_attempt_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExamAttemptService:
    return ExamAttemptService(session)


ExamAttemptServiceDep = Annotated[ExamAttemptService, Depends(get_exam_attempt_service)]


async def _build_detail(
    exam_attempt_service: ExamAttemptService,
    current_user_id: uuid.UUID,
    attempt: ExamAttempt,
) -> ExamAttemptDetailResponse:
    ordered_questions, _ = await exam_attempt_service.get_attempt_questions(attempt)
    answered_ids = await exam_attempt_service.get_answered_question_ids(
        current_user_id, attempt.id
    )
    time_limit_minutes = await exam_attempt_service.get_time_limit_minutes(attempt)
    questions_by_position = {item.question_id: item.position for item in attempt.questions}
    return ExamAttemptDetailResponse(
        id=attempt.id,
        exam_template_id=attempt.exam_template_id,
        status=attempt.status,
        time_limit_minutes=time_limit_minutes,
        total_questions=attempt.total_questions,
        correct_count=attempt.correct_count,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        questions=[
            ExamAttemptQuestionResponse(
                id=question.id,
                statement=question.statement,
                discipline=question.discipline,
                subject=question.subject,
                topic=question.topic,
                difficulty=question.difficulty,
                alternatives=question.alternatives,
                position=questions_by_position[question.id],
                answered=question.id in answered_ids,
            )
            for question in ordered_questions
        ],
    )


@router.post(
    "",
    response_model=Envelope[ExamAttemptDetailResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireFeature(FeatureKey.SIMULADOS))],
)
async def start_exam_attempt(
    body: ExamAttemptStartRequest,
    current_user: CurrentUser,
    exam_attempt_service: ExamAttemptServiceDep,
) -> Envelope[ExamAttemptDetailResponse]:
    attempt = await exam_attempt_service.start_attempt(current_user.id, body.exam_template_id)
    detail = await _build_detail(exam_attempt_service, current_user.id, attempt)
    return Envelope(data=detail)


@router.get("", response_model=Envelope[list[ExamAttemptListItem]])
async def list_exam_attempts(
    current_user: CurrentUser,
    exam_attempt_service: ExamAttemptServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Envelope[list[ExamAttemptListItem]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    attempts = await exam_attempt_service.list_attempts(
        current_user.id, limit=limit, cursor_id=cursor_id
    )
    next_cursor = (
        CursorPage.encode_cursor(str(attempts[-1].id)) if len(attempts) == limit else None
    )

    return Envelope(
        data=[ExamAttemptListItem.model_validate(a) for a in attempts],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )


@router.get("/{attempt_id}", response_model=Envelope[ExamAttemptDetailResponse])
async def get_exam_attempt(
    attempt_id: uuid.UUID,
    current_user: CurrentUser,
    exam_attempt_service: ExamAttemptServiceDep,
) -> Envelope[ExamAttemptDetailResponse]:
    attempt = await exam_attempt_service.get_attempt(attempt_id, current_user.id)
    detail = await _build_detail(exam_attempt_service, current_user.id, attempt)
    return Envelope(data=detail)


@router.post(
    "/{attempt_id}/questions/{question_id}/answer",
    response_model=Envelope[AnswerResultResponse],
)
async def answer_exam_question(
    attempt_id: uuid.UUID,
    question_id: uuid.UUID,
    body: AnswerSubmitRequest,
    current_user: CurrentUser,
    exam_attempt_service: ExamAttemptServiceDep,
) -> Envelope[AnswerResultResponse]:
    answer = await exam_attempt_service.submit_answer(
        user_id=current_user.id,
        attempt_id=attempt_id,
        question_id=question_id,
        data=body,
    )
    question = answer.question
    return Envelope(
        data=AnswerResultResponse(
            question_id=answer.question_id,
            selected_alternative_id=answer.selected_alternative_id,
            correct_alternative_letter=question.correct_alternative_letter,
            is_correct=bool(answer.is_correct),
            explanation=question.explanation,
            teacher_name=question.teacher_name,
        )
    )


@router.post("/{attempt_id}/finish", response_model=Envelope[ExamAttemptDetailResponse])
async def finish_exam_attempt(
    attempt_id: uuid.UUID,
    current_user: CurrentUser,
    exam_attempt_service: ExamAttemptServiceDep,
) -> Envelope[ExamAttemptDetailResponse]:
    attempt = await exam_attempt_service.finish_attempt(attempt_id, current_user.id)
    detail = await _build_detail(exam_attempt_service, current_user.id, attempt)
    return Envelope(data=detail)


@router.post("/{attempt_id}/abandon", response_model=Envelope[ExamAttemptDetailResponse])
async def abandon_exam_attempt(
    attempt_id: uuid.UUID,
    current_user: CurrentUser,
    exam_attempt_service: ExamAttemptServiceDep,
) -> Envelope[ExamAttemptDetailResponse]:
    attempt = await exam_attempt_service.abandon_attempt(attempt_id, current_user.id)
    detail = await _build_detail(exam_attempt_service, current_user.id, attempt)
    return Envelope(data=detail)