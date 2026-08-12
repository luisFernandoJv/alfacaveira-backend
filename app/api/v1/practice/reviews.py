"""Endpoints HTTP de revisões espaçadas."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.practice.review import (
    ReviewResponse,
    ReviewStatsResponse,
)
from app.security.dependencies import CurrentUser
from app.services.practice.review_service import ReviewService

router = APIRouter()


def get_review_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ReviewService:
    return ReviewService(session)


ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]


@router.get("/due", response_model=Envelope[list[ReviewResponse]])
async def list_due_reviews(
    current_user: CurrentUser,
    review_service: ReviewServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Envelope[list[ReviewResponse]]:
    """Lista revisões pendentes para hoje."""
    reviews = await review_service.list_due(current_user.id, limit=limit)
    return Envelope(data=[ReviewResponse.model_validate(r) for r in reviews])


@router.get("/upcoming", response_model=Envelope[list[ReviewResponse]])
async def list_upcoming_reviews(
    current_user: CurrentUser,
    review_service: ReviewServiceDep,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Envelope[list[ReviewResponse]]:
    """Lista revisões futuras (próximos N dias)."""
    reviews = await review_service.list_upcoming(current_user.id, days=days, limit=limit)
    return Envelope(data=[ReviewResponse.model_validate(r) for r in reviews])


@router.get("/stats", response_model=Envelope[ReviewStatsResponse])
async def get_review_stats(
    current_user: CurrentUser,
    review_service: ReviewServiceDep,
) -> Envelope[ReviewStatsResponse]:
    """Estatísticas de revisão do usuário."""
    stats = await review_service.get_stats(current_user.id)
    return Envelope(data=ReviewStatsResponse.model_validate(stats))


@router.post(
    "/schedule",
    response_model=Envelope[list[ReviewResponse]],
    status_code=status.HTTP_201_CREATED,
)
async def schedule_reviews(
    current_user: CurrentUser,
    review_service: ReviewServiceDep,
    question_ids: list[uuid.UUID],
) -> Envelope[list[ReviewResponse]]:
    """Agenda revisões para questões específicas."""
    reviews = await review_service.schedule_batch(
        user_id=current_user.id,
        question_ids=question_ids,
    )
    return Envelope(data=[ReviewResponse.model_validate(r) for r in reviews])


@router.post(
    "/auto-schedule",
    response_model=Envelope[list[ReviewResponse]],
    status_code=status.HTTP_201_CREATED,
)
async def auto_schedule_reviews(
    current_user: CurrentUser,
    review_service: ReviewServiceDep,
) -> Envelope[list[ReviewResponse]]:
    """Agenda revisões automaticamente a partir de questões erradas."""
    reviews = await review_service.auto_schedule_from_errors(current_user.id)
    return Envelope(data=[ReviewResponse.model_validate(r) for r in reviews])


@router.post("/{review_id}/complete", response_model=Envelope[ReviewResponse])
async def complete_review(
    review_id: uuid.UUID,
    current_user: CurrentUser,
    review_service: ReviewServiceDep,
    is_correct: bool,
    time_spent_seconds: Annotated[int | None, Query(ge=0)] = None,
) -> Envelope[ReviewResponse]:
    """Registra a conclusão de uma revisão."""
    review = await review_service.complete_review(
        review_id=review_id,
        user_id=current_user.id,
        is_correct=is_correct,
        time_spent_seconds=time_spent_seconds,
    )
    return Envelope(data=ReviewResponse.model_validate(review))


@router.post("/{review_id}/skip", response_model=Envelope[ReviewResponse])
async def skip_review(
    review_id: uuid.UUID,
    current_user: CurrentUser,
    review_service: ReviewServiceDep,
    skip_until: str | None = None,
) -> Envelope[ReviewResponse]:
    """Pula uma revisão, reagendando para o futuro."""
    from datetime import date
    skip_date = date.fromisoformat(skip_until) if skip_until else None
    
    review = await review_service.skip_review(
        review_id=review_id,
        user_id=current_user.id,
        skip_until=skip_date,
    )
    return Envelope(data=ReviewResponse.model_validate(review))