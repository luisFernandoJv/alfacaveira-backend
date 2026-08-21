"""Repositório de acesso a dados de `Review`."""

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.models.content.question import Question
from app.models.practice.review import Review, ReviewStatus
from app.repositories.base import BaseRepository

_RELATIONS = (
    selectinload(Review.question).selectinload(Question.discipline),
    selectinload(Review.question).selectinload(Question.subject),
    selectinload(Review.question).selectinload(Question.topic),
    selectinload(Review.question).selectinload(Question.exam_board),
    selectinload(Review.question).selectinload(Question.exam_edition),
    selectinload(Review.question).selectinload(Question.organization),
    selectinload(Review.question).selectinload(Question.tags),
    selectinload(Review.question).selectinload(Question.attachments),
)


class ReviewRepository(BaseRepository[Review]):
    model = Review

    async def get_with_question(self, review_id: uuid.UUID) -> Review | None:
        """Busca revisão com a questão carregada."""
        stmt = select(Review).where(Review.id == review_id).options(*_RELATIONS)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned(self, review_id: uuid.UUID, user_id: uuid.UUID) -> Review | None:
        """Busca revisão restrita ao dono."""
        stmt = (
            select(Review)
            .where(Review.id == review_id, Review.user_id == user_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_due(self, user_id: uuid.UUID, limit: int = 50) -> list[Review]:
        """Lista revisões pendentes, ordenadas por prioridade e data de vencimento."""
        today = date.today()
        stmt = (
            select(Review)
            .where(
                Review.user_id == user_id,
                Review.status == ReviewStatus.PENDENTE,
                Review.due_date <= today,
            )
            .options(*_RELATIONS)
            .order_by(
                Review.priority.desc(),
                Review.due_date.asc(),
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_upcoming(self, user_id: uuid.UUID, days: int = 7, limit: int = 50) -> list[Review]:
        """Lista revisões futuras (próximos N dias)."""
        today = date.today()
        future = today + timedelta(days=days)
        stmt = (
            select(Review)
            .where(
                Review.user_id == user_id,
                Review.status == ReviewStatus.PENDENTE,
                Review.due_date > today,
                Review.due_date <= future,
            )
            .options(*_RELATIONS)
            .order_by(Review.due_date.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def count_due(self, user_id: uuid.UUID) -> int:
        """Conta revisões pendentes para hoje."""
        today = date.today()
        stmt = (
            select(func.count())
            .select_from(Review)
            .where(
                Review.user_id == user_id,
                Review.status == ReviewStatus.PENDENTE,
                Review.due_date <= today,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_overdue(self, user_id: uuid.UUID) -> int:
        """Conta revisões atrasadas."""
        today = date.today()
        stmt = (
            select(func.count())
            .select_from(Review)
            .where(
                Review.user_id == user_id,
                Review.status == ReviewStatus.PENDENTE,
                Review.due_date < today,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_completed_today(self, user_id: uuid.UUID) -> int:
        """Conta revisões concluídas hoje."""
        today = date.today()
        stmt = (
            select(func.count())
            .select_from(Review)
            .where(
                Review.user_id == user_id,
                Review.status == ReviewStatus.CONCLUIDA,
                func.date(Review.updated_at) == today,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_status(
        self,
        review_id: uuid.UUID,
        status: ReviewStatus,
        **kwargs,
    ) -> bool:
        """Atualiza status e campos adicionais de uma revisão."""
        values = {"status": status, **kwargs}
        stmt = (
            update(Review)
            .where(Review.id == review_id)
            .values(**values)
        )
        result = await self.session.execute(stmt)
        return result.rowcount == 1

    async def bulk_create(self, reviews: list[Review]) -> list[Review]:
        """Cria múltiplas revisões em lote."""
        for review in reviews:
            self.session.add(review)
        await self.session.flush()
        return reviews

    async def get_stats(self, user_id: uuid.UUID) -> dict:
        """Estatísticas agregadas de revisão."""
        today = date.today()
        thirty_days_ago = today - timedelta(days=30)
        
        total_due = await self.count_due(user_id)
        overdue = await self.count_overdue(user_id)
        completed_today = await self.count_completed_today(user_id)

        # Total de revisões nos últimos 30 dias
        total_stmt = (
            select(func.count())
            .select_from(Review)
            .where(
                Review.user_id == user_id,
                Review.created_at >= thirty_days_ago,
            )
        )
        total_result = await self.session.execute(total_stmt)
        total = total_result.scalar() or 0

        # Revisões concluídas nos últimos 30 dias
        completed_stmt = (
            select(func.count())
            .select_from(Review)
            .where(
                Review.user_id == user_id,
                Review.status == ReviewStatus.CONCLUIDA,
                Review.created_at >= thirty_days_ago,
            )
        )
        completed_result = await self.session.execute(completed_stmt)
        completed = completed_result.scalar() or 0

        completion_rate = round(completed / total * 100, 1) if total > 0 else 0

        # Intervalo médio
        avg_stmt = (
            select(func.avg(Review.interval_days))
            .select_from(Review)
            .where(
                Review.user_id == user_id,
                Review.status == ReviewStatus.CONCLUIDA,
                Review.review_count > 0,
            )
        )
        avg_result = await self.session.execute(avg_stmt)
        avg_interval = avg_result.scalar() or 0

        # Maior sequência de acertos consecutivos
        streak_stmt = (
            select(func.max(Review.consecutive_correct))
            .select_from(Review)
            .where(Review.user_id == user_id)
        )
        streak_result = await self.session.execute(streak_stmt)
        longest_streak = streak_result.scalar() or 0

        return {
            "total_due": total_due,
            "due_today": total_due,
            "overdue": overdue,
            "completed_today": completed_today,
            "completion_rate": completion_rate,
            "average_interval": round(avg_interval, 1) if avg_interval else 0,
            "longest_streak": longest_streak,
        }