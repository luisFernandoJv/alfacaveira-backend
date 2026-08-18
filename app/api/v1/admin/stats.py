import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.models.billing.payment import Payment
from app.models.billing.plan import Plan
from app.models.billing.subscription import Subscription
from app.models.content.question import Question
from app.models.enums import (
    CommentStatus,
    PaymentStatus,
    QuestionStatus,
    SubscriptionStatus,
)
from app.models.identity.user import User
from app.models.platform.comment import Comment
from app.models.platform.question_report import QuestionReport
from app.models.practice.question_attempt import QuestionAttempt
from app.models.practice.training_session import TrainingSession
from app.security.dependencies import CurrentAdminUser

router = APIRouter()


@router.get("/stats", response_model=Envelope[dict])
async def get_admin_stats(
    admin: CurrentAdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[dict]:
    """Estatísticas agregadas da plataforma para o painel /admin/overview.

    Formato de resposta espelha a interface `AdminStats` do frontend
    (app/(app)/admin/overview/page.tsx) — objeto aninhado por domínio,
    não o formato achatado anterior.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start.replace(day=1)

    # --- Usuários ---------------------------------------------------- #
    total_users = await session.scalar(select(func.count()).select_from(User)) or 0
    active_users = await session.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    ) or 0
    new_today = await session.scalar(
        select(func.count()).select_from(User).where(User.created_at >= today_start)
    ) or 0
    new_this_week = await session.scalar(
        select(func.count()).select_from(User).where(User.created_at >= week_start)
    ) or 0

    # --- Questões ------------------------------------------------------ #
    total_questions = await session.scalar(select(func.count()).select_from(Question)) or 0
    publicadas = await session.scalar(
        select(func.count()).select_from(Question).where(Question.status == QuestionStatus.PUBLICADA)
    ) or 0
    rascunho = await session.scalar(
        select(func.count()).select_from(Question).where(Question.status == QuestionStatus.RASCUNHO)
    ) or 0
    em_revisao = await session.scalar(
        select(func.count()).select_from(Question).where(Question.status == QuestionStatus.EM_REVISAO)
    ) or 0
    desativadas = await session.scalar(
        select(func.count()).select_from(Question).where(Question.status == QuestionStatus.DESATIVADA)
    ) or 0

    # --- Treinos --------------------------------------------------------- #
    total_sessions = await session.scalar(select(func.count()).select_from(TrainingSession)) or 0
    total_attempts = await session.scalar(select(func.count()).select_from(QuestionAttempt)) or 0
    correct_attempts = await session.scalar(
        select(func.count()).select_from(QuestionAttempt).where(QuestionAttempt.is_correct.is_(True))
    ) or 0
    avg_accuracy = round((correct_attempts / total_attempts) * 100, 1) if total_attempts else 0.0

    # --- Comentários ------------------------------------------------------ #
    total_comments = await session.scalar(select(func.count()).select_from(Comment)) or 0
    reported_comments = await session.scalar(
        select(func.count()).select_from(Comment).where(Comment.report_count > 0)
    ) or 0
    pending_comment_reports = await session.scalar(
        select(func.count()).select_from(Comment).where(Comment.status == CommentStatus.DENUNCIADO)
    ) or 0

    # --- Reports de questões ----------------------------------------------- #
    report_rows = (
        await session.execute(
            select(QuestionReport.status, func.count()).group_by(QuestionReport.status)
        )
    ).all()
    report_counts = {status: count for status, count in report_rows}
    total_reports = sum(report_counts.values())

    # --- Assinaturas ------------------------------------------------------- #
    active_subs = await session.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.status == SubscriptionStatus.ATIVA)
    ) or 0
    free_users = max(total_users - active_subs, 0)

    plan_rows = (
        await session.execute(
            select(Plan.slug, func.count())
            .select_from(Subscription)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(Subscription.status == SubscriptionStatus.ATIVA)
            .group_by(Plan.slug)
        )
    ).all()
    plan_counts = {slug: count for slug, count in plan_rows}

    revenue_today = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
            Payment.status == PaymentStatus.APROVADO,
            Payment.paid_at >= today_start,
        )
    ) or 0
    revenue_this_month = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
            Payment.status == PaymentStatus.APROVADO,
            Payment.paid_at >= month_start,
        )
    ) or 0

    return Envelope(data={
        "users": {
            "total": total_users,
            "active": active_users,
            "inactive": total_users - active_users,
            "new_today": new_today,
            "new_this_week": new_this_week,
        },
        "questions": {
            "total": total_questions,
            "publicadas": publicadas,
            "rascunho": rascunho,
            "em_revisao": em_revisao,
            "desativadas": desativadas,
        },
        "training": {
            "total_sessions": total_sessions,
            "total_attempts": total_attempts,
            "avg_accuracy": avg_accuracy,
        },
        "comments": {
            "total": total_comments,
            "reported": reported_comments,
            "pending_reports": pending_comment_reports,
        },
        "reports": {
            "total": total_reports,
            "pendente": report_counts.get("pendente", 0),
            "analisando": report_counts.get("analisando", 0),
            "aprovado": report_counts.get("aprovado", 0),
            "rejeitado": report_counts.get("rejeitado", 0),
        },
        "subscriptions": {
            "active": active_subs,
            "free": free_users,
            "standard": plan_counts.get("standard", 0),
            "pro": plan_counts.get("pro", 0),
            "revenue_today": revenue_today,
            "revenue_this_month": revenue_this_month,
        },
    })