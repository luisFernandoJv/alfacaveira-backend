"""Endpoints HTTP de estatísticas agregadas do aluno (analytics).

Todos os endpoints são pessoais (o próprio usuário autenticado) e leem
agregados pré-calculados pelo worker em `app/workers/analytics_aggregator.py`.
Se o worker ainda não produziu dados para um usuário, os endpoints respondem
com listas vazias ou valores zerados — nunca números inventados — para que o
frontend possa exibir corretamente um estado "ainda sem dados".
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.models.enums import FeatureKey
from app.schemas.analytics.user_stats import (
    DashboardResponse,
    DashboardSubjectResponse,
    DashboardTotalsResponse,
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
    days: Annotated[int, Query(ge=1, le=400)] = 7,
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

@router.get(
    "/dashboard",
    response_model=Envelope[DashboardResponse],
    dependencies=[Depends(RequireFeature(FeatureKey.DASHBOARD_COMPLETO))],
)
async def get_dashboard(
    current_user: CurrentUser,
    analytics_service: AnalyticsServiceDep,
    days: Annotated[int, Query(ge=7, le=400)] = 30,
) -> Envelope[DashboardResponse]:
    """Payload agregado para a página de Desempenho.

    Mantém os endpoints antigos intactos e consolida em uma única chamada os
    agregados que a experiência de analytics precisa.
    """
    daily = await analytics_service.get_daily_stats(current_user.id, days=days)
    daily_30 = await analytics_service.get_daily_stats(current_user.id, days=30)
    daily_previous = await analytics_service.get_daily_stats(current_user.id, days=60)
    subjects = await analytics_service.get_subject_performance(current_user.id)
    streak = await analytics_service.get_streak(current_user.id)
    totals = await analytics_service.get_lifetime_totals(current_user.id)
    trends = await analytics_service.get_subject_trends(current_user.id, days=15)
    trend_map = {str(item["discipline_id"]): item["trend"] for item in trends}

    def accuracy(correct: int, total: int) -> float:
        return _accuracy(correct, total)

    current_total = sum(item.questions_answered for item in daily_30)
    current_correct = sum(item.correct_count for item in daily_30)
    current_accuracy = accuracy(current_correct, current_total)
    active_days = sum(1 for item in daily_30 if item.questions_answered > 0)
    current_streak = streak.current_streak if streak else 0
    score = analytics_service.calculate_performance_score(
        accuracy=current_accuracy,
        active_days=active_days,
        streak=current_streak,
    )

    cutoff_30d = datetime.now(UTC).date() - timedelta(days=30)
    previous = [item for item in daily_previous if item.date < cutoff_30d]
    previous_total = sum(item.questions_answered for item in previous)
    previous_correct = sum(item.correct_count for item in previous)
    previous_accuracy = accuracy(previous_correct, previous_total)
    score_change = (
        round(current_accuracy - previous_accuracy, 1)
        if previous_total
        else None
    )

    subject_items = [
        DashboardSubjectResponse(
            discipline=DisciplineResponse.model_validate(stat.discipline),
            questions_answered=stat.questions_answered,
            correct_count=stat.correct_count,
            accuracy=_accuracy(stat.correct_count, stat.questions_answered),
            trend=trend_map.get(str(stat.discipline_id)),
            status=(
                "Forte"
                if _accuracy(stat.correct_count, stat.questions_answered) >= 80
                else "Atenção"
                if _accuracy(stat.correct_count, stat.questions_answered) >= 60
                else "Prioridade"
            ),
        )
        for stat in subjects
    ]

    streak_response = StreakResponse(
        current_streak=current_streak,
        longest_streak=streak.longest_streak if streak else 0,
        last_study_date=streak.last_study_date if streak else None,
    )

    return Envelope(
        data=DashboardResponse(
            score=score,
            score_change_30d=score_change,
            period_accuracy=current_accuracy,
            active_days_30d=active_days,
            totals=DashboardTotalsResponse(**totals),
            daily=[
                DailyStatResponse(
                    date=item.date,
                    questions_answered=item.questions_answered,
                    correct_count=item.correct_count,
                    time_studied_seconds=item.time_studied_seconds,
                    accuracy=_accuracy(item.correct_count, item.questions_answered),
                )
                for item in daily
            ],
            subjects=subject_items,
            streak=streak_response,
        )
    )
