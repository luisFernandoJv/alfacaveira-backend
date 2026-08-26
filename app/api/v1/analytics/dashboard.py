"""Endpoint agregado para a página de Desempenho.

Consolida em uma única chamada o que antes exigia 4 requests separados
(`/today` continua existindo à parte — ele alimenta outras telas como o
Quick Stats do Painel e não faz parte do Performance Score). Não substitui
nenhum dos 4 endpoints existentes em `user_stats.py`: eles continuam
respondendo exatamente como antes, para não quebrar Painel, sidebar e cota
diária, que os consomem diretamente.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.models.enums import FeatureKey
from app.schemas.analytics.dashboard import (
    DashboardResponse,
    DashboardScoreResponse,
    DashboardSubjectResponse,
    DashboardTotalsResponse,
    RecommendationResponse,
)
from app.schemas.analytics.user_stats import DailyStatResponse, StreakResponse
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
    "/dashboard",
    response_model=Envelope[DashboardResponse],
    dependencies=[Depends(RequireFeature(FeatureKey.DASHBOARD_COMPLETO))],
)
async def get_dashboard(
    current_user: CurrentUser,
    analytics_service: AnalyticsServiceDep,
    days: Annotated[int, Query(ge=1, le=400)] = 30,
) -> Envelope[DashboardResponse]:
    """Agregado único que alimenta a página de Desempenho.

    `days` controla apenas a janela retornada em `daily` (o gráfico de
    evolução) — o Performance Score e a variação sempre olham para os
    últimos 30 dias, e a tendência por disciplina sempre olha para os
    últimos 15 dias, independente do filtro escolhido na tela. Teto elevado
    para 400 (era 180 no `/daily`) para suportar o filtro "1 ano" do
    seletor de período.
    """
    bundle = await analytics_service.get_dashboard(current_user.id, days=days)

    subjects = [
        DashboardSubjectResponse(
            discipline=DisciplineResponse.model_validate(item.stat.discipline),
            questions_answered=item.stat.questions_answered,
            correct_count=item.stat.correct_count,
            accuracy=item.accuracy,
            trend=item.trend,
            status=item.status,
        )
        for item in bundle.subjects
    ]

    recommendations = [
        RecommendationResponse(
            discipline_id=rec.discipline_id,
            discipline_name=rec.discipline_name,
            priority=rec.priority,
            reason=rec.reason,
        )
        for rec in bundle.recommendations
    ]

    daily = [
        DailyStatResponse(
            date=stat.date,
            questions_answered=stat.questions_answered,
            correct_count=stat.correct_count,
            time_studied_seconds=stat.time_studied_seconds,
            accuracy=_accuracy(stat.correct_count, stat.questions_answered),
        )
        for stat in bundle.daily
    ]

    streak = bundle.streak
    streak_response = StreakResponse(
        current_streak=streak.current_streak if streak else 0,
        longest_streak=streak.longest_streak if streak else 0,
        last_study_date=streak.last_study_date if streak else None,
    )

    return Envelope(
        data=DashboardResponse(
            score=DashboardScoreResponse(
                value=bundle.score,
                variation_pct=bundle.score_variation_pct,
            ),
            totals_lifetime=DashboardTotalsResponse(
                questions_answered=bundle.totals_lifetime_answered,
                correct_count=bundle.totals_lifetime_correct,
                time_studied_seconds=bundle.totals_lifetime_time_seconds,
                accuracy=_accuracy(
                    bundle.totals_lifetime_correct, bundle.totals_lifetime_answered
                ),
            ),
            streak=streak_response,
            daily=daily,
            subjects=subjects,
            recommendations=recommendations,
            period_start=bundle.period_start,
            period_end=bundle.period_end,
        )
    )