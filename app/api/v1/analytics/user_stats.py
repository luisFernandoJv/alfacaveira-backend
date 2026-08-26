"""Endpoints HTTP de estatísticas agregadas do aluno (analytics).

Todos os endpoints são pessoais (o próprio usuário autenticado) e leem
agregados pré-calculados por um worker em background que ainda não existe
(`app/workers` está vazio hoje). Enquanto isso, os endpoints respondem com
listas vazias ou valores zerados — nunca números inventados — para que o
frontend possa exibir corretamente um estado "ainda sem dados".
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.models.enums import FeatureKey
from app.schemas.analytics.user_stats import (
    DailyStatResponse,
    StreakResponse,
    SubjectStatResponse,
    TodayStatResponse,
)
from app.schemas.content.taxonomy import DisciplineResponse
from app.security.dependencies import CurrentUser, RequireFeature
from app.services.analytics.analytics_service import AnalyticsService

router = APIRouter()


def get_analytics_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AnalyticsService:
    return AnalyticsService(session)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total * 100, 1) if total else 0.0


@router.get(
    "/daily",
    response_model=Envelope[list[DailyStatResponse]],
    dependencies=[Depends(RequireFeature(FeatureKey.DASHBOARD_COMPLETO))],
)
async def list_daily_stats(
    current_user: CurrentUser,
    analytics_service: AnalyticsServiceDep,
    days: Annotated[int, Query(ge=1, le=180)] = 7,
) -> Envelope[list[DailyStatResponse]]:
    """Série diária dos últimos `days` dias — alimenta a Evolução Semanal."""
    stats = await analytics_service.get_daily_stats(current_user.id, days=days)
    return Envelope(
        data=[
            DailyStatResponse(
                date=stat.date,
                questions_answered=stat.questions_answered,
                correct_count=stat.correct_count,
                time_studied_seconds=stat.time_studied_seconds,
                accuracy=_accuracy(stat.correct_count, stat.questions_answered),
            )
            for stat in stats
        ]
    )


@router.get(
    "/today",
    response_model=Envelope[TodayStatResponse],
    dependencies=[Depends(RequireFeature(FeatureKey.ESTATISTICAS))],
)
async def get_today_stat(
    current_user: CurrentUser,
    analytics_service: AnalyticsServiceDep,
) -> Envelope[TodayStatResponse]:
    """Atividade do dia corrente — alimenta o card 'Questões hoje' do Quick Stats."""
    stat = await analytics_service.get_today_stat(current_user.id)
    if stat is None:
        return Envelope(
            data=TodayStatResponse(
                questions_answered=0,
                correct_count=0,
                time_studied_seconds=0,
                accuracy=0.0,
            )
        )
    return Envelope(
        data=TodayStatResponse(
            questions_answered=stat.questions_answered,
            correct_count=stat.correct_count,
            time_studied_seconds=stat.time_studied_seconds,
            accuracy=_accuracy(stat.correct_count, stat.questions_answered),
        )
    )


@router.get(
    "/subjects",
    response_model=Envelope[list[SubjectStatResponse]],
    dependencies=[Depends(RequireFeature(FeatureKey.DASHBOARD_COMPLETO))],
)
async def list_subject_stats(
    current_user: CurrentUser,
    analytics_service: AnalyticsServiceDep,
) -> Envelope[list[SubjectStatResponse]]:
    """Desempenho por disciplina — alimenta o card 'Desempenho por disciplina'."""
    stats = await analytics_service.get_subject_performance(current_user.id)
    return Envelope(
        data=[
            SubjectStatResponse(
                discipline=DisciplineResponse.model_validate(stat.discipline),
                questions_answered=stat.questions_answered,
                correct_count=stat.correct_count,
                accuracy=_accuracy(stat.correct_count, stat.questions_answered),
            )
            for stat in stats
        ]
    )


@router.get(
    "/streak",
    response_model=Envelope[StreakResponse],
    dependencies=[Depends(RequireFeature(FeatureKey.ESTATISTICAS))],
)
async def get_streak(
    current_user: CurrentUser,
    analytics_service: AnalyticsServiceDep,
) -> Envelope[StreakResponse]:
    """Sequência de dias estudados — alimenta o badge de streak do GreetingHeader."""
    streak = await analytics_service.get_streak(current_user.id)
    if streak is None:
        return Envelope(
            data=StreakResponse(current_streak=0, longest_streak=0, last_study_date=None)
        )
    return Envelope(
        data=StreakResponse(
            current_streak=streak.current_streak,
            longest_streak=streak.longest_streak,
            last_study_date=streak.last_study_date,
        )
    )