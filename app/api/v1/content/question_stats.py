"""Endpoint de estatísticas do banco de questões para o usuário autenticado."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.models.content.question import Question
from app.models.enums import QuestionStatus
from app.models.practice.question_attempt import QuestionAttempt
from app.models.practice.user_question_state import UserQuestionState
from app.repositories.practice.user_question_state_repository import UserQuestionStateRepository
from app.security.dependencies import CurrentUser

router = APIRouter()


@router.get("/stats", response_model=Envelope[dict])
async def get_question_stats(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[dict]:
    """
    Retorna estatísticas do banco de questões para o usuário autenticado.

    - total: total de questões publicadas
    - answered: questões respondidas pelo usuário
    - correct: questões acertadas
    - accuracy: taxa de acerto (%)
    - favorites: questões favoritadas
    """

    # Total de questões publicadas
    total_stmt = select(func.count()).select_from(Question).where(
        Question.status == QuestionStatus.PUBLICADA
    )
    total_result = await session.execute(total_stmt)
    total = total_result.scalar() or 0

    # Questões respondidas (tentativas do usuário)
    answered_stmt = select(func.count()).select_from(QuestionAttempt).where(
        QuestionAttempt.user_id == current_user.id
    )
    answered_result = await session.execute(answered_stmt)
    answered = answered_result.scalar() or 0

    # Questões corretas
    correct_stmt = select(func.count()).select_from(QuestionAttempt).where(
        QuestionAttempt.user_id == current_user.id,
        QuestionAttempt.is_correct.is_(True),
    )
    correct_result = await session.execute(correct_stmt)
    correct = correct_result.scalar() or 0

    # Favoritos
    state_repo = UserQuestionStateRepository(session)
    favorites = await state_repo.list_favorites(
        user_id=current_user.id,
        limit=1000,
        cursor_id=None,
    )

    accuracy = round((correct / answered * 100) if answered > 0 else 0, 1)

    return Envelope(
        data={
            "total": total,
            "answered": answered,
            "correct": correct,
            "accuracy": accuracy,
            "favorites": len(favorites),
        }
    )