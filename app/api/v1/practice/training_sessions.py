"""Endpoints HTTP de sessões de treino.

Todos os endpoints são pessoais (o próprio usuário autenticado) — treino não
tem conceito de administração; qualquer usuário ativo pode criar e responder
suas próprias sessões.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.models.practice.training_session import TrainingSession
from app.schemas.practice.question_attempt import AnswerResultResponse, AnswerSubmitRequest
from app.schemas.practice.training_session import (
    TrainingSessionCreateRequest,
    TrainingSessionDetailResponse,
    TrainingSessionListItem,
    TrainingSessionPositionResponse,
    TrainingSessionPositionUpdateRequest,
    TrainingSessionQuestionResponse,
)
from app.security.dependencies import CurrentUser
from app.services.practice.question_attempt_service import QuestionAttemptService
from app.services.practice.training_session_service import TrainingSessionService

router = APIRouter()


def get_training_session_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TrainingSessionService:
    return TrainingSessionService(session)


def get_question_attempt_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> QuestionAttemptService:
    return QuestionAttemptService(session)


TrainingSessionServiceDep = Annotated[
    TrainingSessionService, Depends(get_training_session_service)
]
QuestionAttemptServiceDep = Annotated[
    QuestionAttemptService, Depends(get_question_attempt_service)
]


async def _build_detail(
    training_session_service: TrainingSessionService,
    current_user_id: uuid.UUID,
    training_session: TrainingSession,
) -> TrainingSessionDetailResponse:
    ordered_questions, _ = await training_session_service.get_session_questions(training_session)
    answered_ids = await training_session_service.get_answered_question_ids(
        current_user_id, training_session.id
    )
    questions_by_position = {
        item.question_id: item.position for item in training_session.questions
    }
    return TrainingSessionDetailResponse(
        id=training_session.id,
        total_questions=training_session.total_questions,
        correct_count=training_session.correct_count,
        started_at=training_session.started_at,
        finished_at=training_session.finished_at,
        current_question_index=training_session.current_question_index,
        questions=[
            TrainingSessionQuestionResponse(
                id=question.id,
                statement=question.statement,
                discipline=question.discipline,
                subject=question.subject,
                topic=question.topic,
                exam_board=question.exam_board,
                exam_edition=question.exam_edition,
                organization=question.organization,
                year=question.year,
                difficulty=question.difficulty,
                alternatives=question.alternatives,
                tags=question.tags,
                position=questions_by_position[question.id],
                answered=question.id in answered_ids,
            )
            for question in ordered_questions
        ],
    )


@router.post(
    "", response_model=Envelope[TrainingSessionDetailResponse], status_code=status.HTTP_201_CREATED
)
async def create_training_session(
    body: TrainingSessionCreateRequest,
    current_user: CurrentUser,
    training_session_service: TrainingSessionServiceDep,
) -> Envelope[TrainingSessionDetailResponse]:
    training_session = await training_session_service.create_session(current_user.id, body)
    detail = await _build_detail(training_session_service, current_user.id, training_session)
    return Envelope(data=detail)


@router.get("", response_model=Envelope[list[TrainingSessionListItem]])
async def list_training_sessions(
    current_user: CurrentUser,
    training_session_service: TrainingSessionServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Envelope[list[TrainingSessionListItem]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    sessions = await training_session_service.list_sessions(
        current_user.id, limit=limit, cursor_id=cursor_id
    )
    next_cursor = (
        CursorPage.encode_cursor(str(sessions[-1].id)) if len(sessions) == limit else None
    )

    return Envelope(
        data=[TrainingSessionListItem.model_validate(s) for s in sessions],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )


@router.get("/{session_id}", response_model=Envelope[TrainingSessionDetailResponse])
async def get_training_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    training_session_service: TrainingSessionServiceDep,
) -> Envelope[TrainingSessionDetailResponse]:
    training_session = await training_session_service.get_session(session_id, current_user.id)
    detail = await _build_detail(training_session_service, current_user.id, training_session)
    return Envelope(data=detail)


@router.post(
    "/{session_id}/questions/{question_id}/answer",
    response_model=Envelope[AnswerResultResponse],
)
async def answer_training_question(
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    body: AnswerSubmitRequest,
    current_user: CurrentUser,
    question_attempt_service: QuestionAttemptServiceDep,
) -> Envelope[AnswerResultResponse]:
    attempt = await question_attempt_service.submit_training_answer(
        user_id=current_user.id,
        session_id=session_id,
        question_id=question_id,
        data=body,
    )
    question = attempt.question
    return Envelope(
        data=AnswerResultResponse(
            question_id=attempt.question_id,
            selected_alternative_id=attempt.selected_alternative_id,
            correct_alternative_letter=question.correct_alternative_letter,
            is_correct=bool(attempt.is_correct),
            explanation=question.explanation,
        )
    )


@router.patch(
    "/{session_id}/position",
    response_model=Envelope[TrainingSessionPositionResponse],
    summary="Atualiza a posição (questão atual) da sessão",
)
async def update_training_session_position(
    session_id: uuid.UUID,
    body: TrainingSessionPositionUpdateRequest,
    current_user: CurrentUser,
    training_session_service: TrainingSessionServiceDep,
) -> Envelope[TrainingSessionPositionResponse]:
    training_session = await training_session_service.update_position(
        session_id, current_user.id, body.current_question_index
    )
    return Envelope(
        data=TrainingSessionPositionResponse.model_validate(training_session)
    )


@router.post("/{session_id}/finish", response_model=Envelope[TrainingSessionDetailResponse])
async def finish_training_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    training_session_service: TrainingSessionServiceDep,
) -> Envelope[TrainingSessionDetailResponse]:
    training_session = await training_session_service.finish_session(session_id, current_user.id)
    detail = await _build_detail(training_session_service, current_user.id, training_session)
    return Envelope(data=detail)