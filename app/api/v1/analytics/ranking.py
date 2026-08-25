"""Endpoints HTTP de ranking."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.analytics.ranking import (
    RankingPositionResponse,
    RankingResponse,
    UserRankingResponse,
)
from app.security.dependencies import CurrentUser
from app.services.analytics.ranking_service import RankingService

router = APIRouter()


def get_ranking_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RankingService:
    return RankingService(session)


RankingServiceDep = Annotated[RankingService, Depends(get_ranking_service)]


@router.get("/global", response_model=Envelope[RankingResponse])
async def get_global_ranking(
    current_user: CurrentUser,
    ranking_service: RankingServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[RankingResponse]:
    """
    Ranking global de todos os usuários.

    Retorna os usuários com mais pontos, ordenados por posição.
    Inclui a posição do usuário atual.
    """
    rankings, user_position, total, has_more = await ranking_service.get_global_ranking(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    return Envelope(
        data=RankingResponse(
            items=[RankingPositionResponse.from_model(r) for r in rankings],
            total=total,
            user_position=user_position,
            has_more=has_more,
        )
    )


@router.get("/weekly", response_model=Envelope[RankingResponse])
async def get_weekly_ranking(
    current_user: CurrentUser,
    ranking_service: RankingServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[RankingResponse]:
    """Ranking semanal."""
    rankings, user_position, total, has_more = await ranking_service.get_weekly_ranking(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    return Envelope(
        data=RankingResponse(
            items=[RankingPositionResponse.from_model(r) for r in rankings],
            total=total,
            user_position=user_position,
            has_more=has_more,
        )
    )


@router.get("/monthly", response_model=Envelope[RankingResponse])
async def get_monthly_ranking(
    current_user: CurrentUser,
    ranking_service: RankingServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[RankingResponse]:
    """Ranking mensal."""
    rankings, user_position, total, has_more = await ranking_service.get_monthly_ranking(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    return Envelope(
        data=RankingResponse(
            items=[RankingPositionResponse.from_model(r) for r in rankings],
            total=total,
            user_position=user_position,
            has_more=has_more,
        )
    )


@router.get("/me", response_model=Envelope[UserRankingResponse | None])
async def get_my_ranking(
    current_user: CurrentUser,
    ranking_service: RankingServiceDep,
) -> Envelope[UserRankingResponse | None]:
    """Posição do usuário no ranking."""
    ranking = await ranking_service.get_user_ranking(current_user.id)
    if not ranking:
        return Envelope(data=None)
    return Envelope(data=UserRankingResponse.model_validate(ranking))


@router.post("/update", status_code=status.HTTP_204_NO_CONTENT)
async def update_rankings(
    current_user: CurrentUser,
    ranking_service: RankingServiceDep,
) -> None:
    """
    Atualiza o ranking de todos os usuários.

    Esta rota é protegida e deve ser usada com moderação.
    O worker já faz a atualização automática.
    """
    await ranking_service.update_all_rankings()