"""Endpoint de histórico geral de tentativas de resposta do usuário.

Cobre todas as origens (`treino`, e futuramente `simulado`) — mesma tabela
unificada `QuestionAttempt`, conforme decisão de modelagem da Etapa 8.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.schemas.practice.question_attempt import QuestionAttemptListItem
from app.security.dependencies import CurrentUser
from app.services.practice.question_attempt_service import QuestionAttemptService

router = APIRouter()


def get_question_attempt_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> QuestionAttemptService:
    return QuestionAttemptService(session)


QuestionAttemptServiceDep = Annotated[
    QuestionAttemptService, Depends(get_question_attempt_service)
]


@router.get("", response_model=Envelope[list[QuestionAttemptListItem]])
async def list_attempts(
    current_user: CurrentUser,
    question_attempt_service: QuestionAttemptServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Envelope[list[QuestionAttemptListItem]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    attempts = await question_attempt_service.list_history(
        current_user.id, limit=limit, cursor_id=cursor_id
    )
    next_cursor = (
        CursorPage.encode_cursor(str(attempts[-1].id)) if len(attempts) == limit else None
    )

    return Envelope(
        data=[QuestionAttemptListItem.model_validate(a) for a in attempts],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )
