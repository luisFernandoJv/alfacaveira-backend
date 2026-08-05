"""Endpoints HTTP de questões.

Listagem e detalhe são públicos (qualquer usuário autenticado); CRUD é
restrito a administradores (`CurrentAdminUser`) — não existe papel
"editor" separado no modelo de usuário atual.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.models.enums import QuestionDifficulty, QuestionStatus
from app.repositories.content.question_repository import QuestionFilters
from app.schemas.content.question import (
    QuestionCreateRequest,
    QuestionDetailResponse,
    QuestionListItem,
    QuestionStatusUpdateRequest,
    QuestionUpdateRequest,
)
from app.security.dependencies import CurrentAdminUser, CurrentUser
from app.services.content.question_service import QuestionService

router = APIRouter()


def get_question_service(session: Annotated[AsyncSession, Depends(get_db)]) -> QuestionService:
    return QuestionService(session)


QuestionServiceDep = Annotated[QuestionService, Depends(get_question_service)]


@router.get("", response_model=Envelope[list[QuestionListItem]])
async def list_questions(
    _current_user: CurrentUser,
    question_service: QuestionServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    discipline_id: Annotated[uuid.UUID | None, Query()] = None,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
    topic_id: Annotated[uuid.UUID | None, Query()] = None,
    exam_board_id: Annotated[uuid.UUID | None, Query()] = None,
    exam_edition_id: Annotated[uuid.UUID | None, Query()] = None,
    organization_id: Annotated[uuid.UUID | None, Query()] = None,
    year: Annotated[int | None, Query()] = None,
    difficulty: Annotated[QuestionDifficulty | None, Query()] = None,
    tag_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    question_status: Annotated[
        QuestionStatus | None, Query(alias="status")
    ] = QuestionStatus.PUBLICADA,
) -> Envelope[list[QuestionListItem]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    filters = QuestionFilters(
        discipline_id=discipline_id,
        subject_id=subject_id,
        topic_id=topic_id,
        exam_board_id=exam_board_id,
        exam_edition_id=exam_edition_id,
        organization_id=organization_id,
        year=year,
        difficulty=difficulty,
        status=question_status,
        tag_id=tag_id,
        search=search,
    )
    questions = await question_service.list_questions(
        limit=limit, cursor_id=cursor_id, filters=filters
    )
    next_cursor = (
        CursorPage.encode_cursor(str(questions[-1].id)) if len(questions) == limit else None
    )

    return Envelope(
        data=[QuestionListItem.model_validate(q) for q in questions],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )


@router.get("/{question_id}", response_model=Envelope[QuestionDetailResponse])
async def get_question(
    question_id: uuid.UUID,
    _current_user: CurrentUser,
    question_service: QuestionServiceDep,
) -> Envelope[QuestionDetailResponse]:
    question = await question_service.get_question(question_id)
    return Envelope(data=QuestionDetailResponse.model_validate(question))


@router.post(
    "", response_model=Envelope[QuestionDetailResponse], status_code=status.HTTP_201_CREATED
)
async def create_question(
    body: QuestionCreateRequest,
    admin: CurrentAdminUser,
    question_service: QuestionServiceDep,
) -> Envelope[QuestionDetailResponse]:
    question = await question_service.create_question(admin.id, body)
    return Envelope(data=QuestionDetailResponse.model_validate(question))


@router.patch("/{question_id}", response_model=Envelope[QuestionDetailResponse])
async def update_question(
    question_id: uuid.UUID,
    body: QuestionUpdateRequest,
    admin: CurrentAdminUser,
    question_service: QuestionServiceDep,
) -> Envelope[QuestionDetailResponse]:
    question = await question_service.update_question(question_id, admin.id, body)
    return Envelope(data=QuestionDetailResponse.model_validate(question))


@router.patch("/{question_id}/status", response_model=Envelope[QuestionDetailResponse])
async def update_question_status(
    question_id: uuid.UUID,
    body: QuestionStatusUpdateRequest,
    admin: CurrentAdminUser,
    question_service: QuestionServiceDep,
) -> Envelope[QuestionDetailResponse]:
    question = await question_service.update_status(question_id, admin.id, body.status)
    return Envelope(data=QuestionDetailResponse.model_validate(question))


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: uuid.UUID,
    admin: CurrentAdminUser,
    question_service: QuestionServiceDep,
) -> None:
    await question_service.delete_question(question_id, admin.id)
