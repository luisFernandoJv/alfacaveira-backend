"""Endpoints HTTP de flashcards e revisão espaçada (SM-2).

Todos os endpoints são privados ao usuário autenticado (`CurrentUser`): um
flashcard só pode ser visto/editado/revisado pelo dono.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.repositories.learning.flashcard_repository import FlashcardFilters
from app.schemas.learning.flashcard import (
    FlashcardCreateFromQuestionRequest,
    FlashcardCreateRequest,
    FlashcardResponse,
    FlashcardReviewRequest,
    FlashcardStatsResponse,
    FlashcardUpdateRequest,
)
from app.security.dependencies import CurrentUser
from app.services.learning.flashcard_service import FlashcardService

router = APIRouter()


def get_flashcard_service(session: Annotated[AsyncSession, Depends(get_db)]) -> FlashcardService:
    return FlashcardService(session)


FlashcardServiceDep = Annotated[FlashcardService, Depends(get_flashcard_service)]


@router.get("", response_model=Envelope[list[FlashcardResponse]])
async def list_flashcards(
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    discipline_id: Annotated[uuid.UUID | None, Query()] = None,
    question_id: Annotated[uuid.UUID | None, Query()] = None,
    due_only: Annotated[bool, Query()] = False,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Envelope[list[FlashcardResponse]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    filters = FlashcardFilters(
        user_id=current_user.id,
        discipline_id=discipline_id,
        question_id=question_id,
        due_only=due_only,
        search=search,
    )
    flashcards = await flashcard_service.list_flashcards(limit=limit, cursor_id=cursor_id, filters=filters)
    next_cursor = (
        CursorPage.encode_cursor(str(flashcards[-1].id)) if len(flashcards) == limit else None
    )

    return Envelope(
        data=[FlashcardResponse.from_model(card) for card in flashcards],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None, total=len(flashcards)),
    )


@router.get("/due", response_model=Envelope[list[FlashcardResponse]])
async def list_due_flashcards(
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Envelope[list[FlashcardResponse]]:
    """Flashcards pendentes de revisão hoje (`due_date <= hoje`)."""
    flashcards = await flashcard_service.list_due(current_user.id, limit=limit)
    return Envelope(data=[FlashcardResponse.from_model(card) for card in flashcards])


@router.get("/stats", response_model=Envelope[FlashcardStatsResponse])
async def get_flashcard_stats(
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> Envelope[FlashcardStatsResponse]:
    stats = await flashcard_service.get_stats(current_user.id)
    return Envelope(data=stats)


@router.get("/by-question/{question_id}", response_model=Envelope[list[FlashcardResponse]])
async def list_flashcards_by_question(
    question_id: uuid.UUID,
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> Envelope[list[FlashcardResponse]]:
    flashcards = await flashcard_service.list_by_question(question_id, current_user.id)
    return Envelope(data=[FlashcardResponse.from_model(card) for card in flashcards])


@router.get("/by-discipline/{discipline_id}", response_model=Envelope[list[FlashcardResponse]])
async def list_flashcards_by_discipline(
    discipline_id: uuid.UUID,
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> Envelope[list[FlashcardResponse]]:
    flashcards = await flashcard_service.list_by_discipline(discipline_id, current_user.id)
    return Envelope(data=[FlashcardResponse.from_model(card) for card in flashcards])


@router.get("/{flashcard_id}", response_model=Envelope[FlashcardResponse])
async def get_flashcard(
    flashcard_id: uuid.UUID,
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> Envelope[FlashcardResponse]:
    flashcard = await flashcard_service.get_flashcard(flashcard_id, current_user.id)
    return Envelope(data=FlashcardResponse.from_model(flashcard))


@router.post("", response_model=Envelope[FlashcardResponse], status_code=status.HTTP_201_CREATED)
async def create_flashcard(
    body: FlashcardCreateRequest,
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> Envelope[FlashcardResponse]:
    flashcard = await flashcard_service.create_flashcard(current_user.id, body)
    return Envelope(data=FlashcardResponse.from_model(flashcard))


@router.post(
    "/from-question",
    response_model=Envelope[FlashcardResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_flashcard_from_question(
    body: FlashcardCreateFromQuestionRequest,
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> Envelope[FlashcardResponse]:
    """Cria um flashcard automaticamente a partir de uma questão respondida."""
    flashcard = await flashcard_service.create_from_question(current_user.id, body)
    return Envelope(data=FlashcardResponse.from_model(flashcard))


@router.put("/{flashcard_id}", response_model=Envelope[FlashcardResponse])
async def update_flashcard(
    flashcard_id: uuid.UUID,
    body: FlashcardUpdateRequest,
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> Envelope[FlashcardResponse]:
    flashcard = await flashcard_service.update_flashcard(flashcard_id, current_user.id, body)
    return Envelope(data=FlashcardResponse.from_model(flashcard))


@router.delete("/{flashcard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flashcard(
    flashcard_id: uuid.UUID,
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> None:
    await flashcard_service.delete_flashcard(flashcard_id, current_user.id)


@router.post("/{flashcard_id}/review", response_model=Envelope[FlashcardResponse])
async def review_flashcard(
    flashcard_id: uuid.UUID,
    body: FlashcardReviewRequest,
    current_user: CurrentUser,
    flashcard_service: FlashcardServiceDep,
) -> Envelope[FlashcardResponse]:
    """Registra a avaliação de confiança do aluno e recalcula o agendamento (SM-2)."""
    flashcard = await flashcard_service.review_flashcard(flashcard_id, current_user.id, body.grade)
    return Envelope(data=FlashcardResponse.from_model(flashcard))