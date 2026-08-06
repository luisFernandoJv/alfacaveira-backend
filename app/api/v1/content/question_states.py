"""Endpoints HTTP de estado do usuário por questão (favoritos e anotações).

Todos os endpoints são pessoais — operam sempre sobre o usuário autenticado.

Rotas:
  GET    /questions/{question_id}/state         → estado atual
  PUT    /questions/{question_id}/state/favorite → alterna favorito
  PUT    /questions/{question_id}/state/note     → salva/apaga anotação
  GET    /questions/favorites                    → lista paginada de favoritas
  GET    /questions/notes                        → lista paginada com anotação
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.schemas.practice.user_question_state import (
    FavoriteToggleRequest,
    NoteUpsertRequest,
    UserQuestionStateResponse,
)
from app.security.dependencies import CurrentUser
from app.services.practice.user_question_state_service import UserQuestionStateService

router = APIRouter()


def get_state_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserQuestionStateService:
    return UserQuestionStateService(session)


StateServiceDep = Annotated[UserQuestionStateService, Depends(get_state_service)]

# --------------------------------------------------------------------------- #
# Leitura por questão                                                          #
# --------------------------------------------------------------------------- #


@router.get(
    "/{question_id}/state",
    response_model=Envelope[UserQuestionStateResponse | None],
    summary="Estado do usuário para uma questão",
)
async def get_question_state(
    question_id: uuid.UUID,
    current_user: CurrentUser,
    state_service: StateServiceDep,
) -> Envelope[UserQuestionStateResponse | None]:
    state = await state_service.get_state(current_user.id, question_id)
    data = UserQuestionStateResponse.model_validate(state) if state else None
    return Envelope(data=data)


# --------------------------------------------------------------------------- #
# Favorito                                                                     #
# --------------------------------------------------------------------------- #


@router.put(
    "/{question_id}/state/favorite",
    response_model=Envelope[UserQuestionStateResponse],
    status_code=status.HTTP_200_OK,
    summary="Favoritar / desfavoritar questão",
)
async def toggle_favorite(
    question_id: uuid.UUID,
    body: FavoriteToggleRequest,
    current_user: CurrentUser,
    state_service: StateServiceDep,
) -> Envelope[UserQuestionStateResponse]:
    state = await state_service.toggle_favorite(current_user.id, question_id, body)
    return Envelope(data=UserQuestionStateResponse.model_validate(state))


# --------------------------------------------------------------------------- #
# Anotação pessoal                                                             #
# --------------------------------------------------------------------------- #


@router.put(
    "/{question_id}/state/note",
    response_model=Envelope[UserQuestionStateResponse],
    status_code=status.HTTP_200_OK,
    summary="Salvar ou apagar anotação pessoal",
)
async def upsert_note(
    question_id: uuid.UUID,
    body: NoteUpsertRequest,
    current_user: CurrentUser,
    state_service: StateServiceDep,
) -> Envelope[UserQuestionStateResponse]:
    state = await state_service.upsert_note(current_user.id, question_id, body)
    return Envelope(data=UserQuestionStateResponse.model_validate(state))


# --------------------------------------------------------------------------- #
# Listagens globais (favoritas / anotadas)                                    #
# --------------------------------------------------------------------------- #


@router.get(
    "/favorites",
    response_model=Envelope[list[UserQuestionStateResponse]],
    summary="Questões favoritadas pelo usuário (paginado)",
)
async def list_favorites(
    current_user: CurrentUser,
    state_service: StateServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Envelope[list[UserQuestionStateResponse]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded = page.decode_cursor()
    cursor_id = uuid.UUID(decoded) if decoded else None

    states = await state_service.list_favorites(current_user.id, limit=limit, cursor_id=cursor_id)
    next_cursor = (
        CursorPage.encode_cursor(str(states[-1].id)) if len(states) == limit else None
    )
    return Envelope(
        data=[UserQuestionStateResponse.model_validate(s) for s in states],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )


@router.get(
    "/notes",
    response_model=Envelope[list[UserQuestionStateResponse]],
    summary="Questões com anotação pessoal (paginado)",
)
async def list_notes(
    current_user: CurrentUser,
    state_service: StateServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Envelope[list[UserQuestionStateResponse]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded = page.decode_cursor()
    cursor_id = uuid.UUID(decoded) if decoded else None

    states = await state_service.list_noted(current_user.id, limit=limit, cursor_id=cursor_id)
    next_cursor = (
        CursorPage.encode_cursor(str(states[-1].id)) if len(states) == limit else None
    )
    return Envelope(
        data=[UserQuestionStateResponse.model_validate(s) for s in states],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )