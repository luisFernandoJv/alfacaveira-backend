"""Regras de negócio de revisões espaçadas."""

import uuid
from datetime import date, datetime, timedelta
from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.enums import ReviewPriority, ReviewStatus
from app.models.practice.review import Review
from app.repositories.content.question_repository import QuestionRepository
from app.repositories.practice.review_repository import ReviewRepository


class ReviewService:
    """Serviço de revisão espaçada de questões."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._reviews = ReviewRepository(session)
        self._questions = QuestionRepository(session)

    # ==================================================================== #
    # LEITURA
    # ==================================================================== #

    async def get_review(self, review_id: uuid.UUID, user_id: uuid.UUID) -> Review:
        """Busca uma revisão específica."""
        review = await self._reviews.get_owned(review_id, user_id)
        if review is None:
            raise NotFoundError("Revisão não encontrada.")
        return review

    async def list_due(self, user_id: uuid.UUID, limit: int = 50) -> list[Review]:
        """Lista revisões pendentes para hoje."""
        return await self._reviews.list_due(user_id, limit=limit)

    async def list_upcoming(self, user_id: uuid.UUID, days: int = 7, limit: int = 50) -> list[Review]:
        """Lista revisões futuras."""
        return await self._reviews.list_upcoming(user_id, days=days, limit=limit)

    async def get_stats(self, user_id: uuid.UUID) -> dict:
        """Retorna estatísticas de revisão do usuário."""
        return await self._reviews.get_stats(user_id)

    # ==================================================================== #
    # CRIAÇÃO
    # ==================================================================== #

    async def schedule_review(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
        priority: ReviewPriority = ReviewPriority.MEDIA,
        due_date: date | None = None,
    ) -> Review:
        """Agenda uma nova revisão para uma questão."""

        # Verifica se já existe uma revisão pendente para esta questão
        existing = await self._reviews.list_due(user_id)
        for review in existing:
            if review.question_id == question_id:
                raise ConflictError("Já existe uma revisão pendente para esta questão.")

        # Verifica se a questão existe
        question = await self._questions.get_by_id(question_id)
        if question is None:
            raise NotFoundError("Questão não encontrada.")

        # Calcula data de vencimento
        if due_date is None:
            due_date = date.today()

        review = Review(
            user_id=user_id,
            question_id=question_id,
            status=ReviewStatus.PENDENTE,
            priority=priority,
            due_date=due_date,
            review_count=0,
            consecutive_correct=0,
            interval_days=1,
        )

        async with UnitOfWork(self._session):
            await self._reviews.add(review)

        return await self._reviews.get_with_question(review.id)

    async def schedule_batch(
        self,
        user_id: uuid.UUID,
        question_ids: list[uuid.UUID],
        priority: ReviewPriority = ReviewPriority.MEDIA,
    ) -> list[Review]:
        """Agenda múltiplas revisões em lote."""
        reviews = []
        today = date.today()

        for question_id in question_ids:
            review = Review(
                user_id=user_id,
                question_id=question_id,
                status=ReviewStatus.PENDENTE,
                priority=priority,
                due_date=today,
                review_count=0,
                consecutive_correct=0,
                interval_days=1,
            )
            reviews.append(review)

        async with UnitOfWork(self._session):
            await self._reviews.bulk_create(reviews)

        # Recarrega com as questões
        result = []
        for review in reviews:
            loaded = await self._reviews.get_with_question(review.id)
            if loaded:
                result.append(loaded)

        return result

    # ==================================================================== #
    # INTERAÇÃO
    # ==================================================================== #

    async def complete_review(
        self,
        review_id: uuid.UUID,
        user_id: uuid.UUID,
        is_correct: bool,
        time_spent_seconds: int | None = None,
    ) -> Review:
        """Registra a conclusão de uma revisão e calcula o próximo agendamento."""

        review = await self.get_review(review_id, user_id)

        if review.status != ReviewStatus.PENDENTE:
            raise ConflictError("Esta revisão já foi concluída ou pulada.")

        # Atualiza estatísticas
        new_count = review.review_count + 1
        new_consecutive = review.consecutive_correct + 1 if is_correct else 0

        # Calcula novo intervalo (SM-2 simplificado)
        if is_correct:
            if new_count == 1:
                new_interval = 1
            elif new_count == 2:
                new_interval = 3
            else:
                new_interval = min(int(review.interval_days * 2.5), 365)
        else:
            new_interval = max(1, review.interval_days // 2)

        # Calcula nova prioridade
        if not is_correct:
            new_priority = ReviewPriority.ALTA
        elif new_consecutive >= 3:
            new_priority = ReviewPriority.BAIXA
        elif new_consecutive >= 1:
            new_priority = ReviewPriority.MEDIA
        else:
            new_priority = ReviewPriority.ALTA

        # Nova data de vencimento
        new_due_date = date.today() + timedelta(days=new_interval)

        async with UnitOfWork(self._session):
            review.status = ReviewStatus.CONCLUIDA
            review.review_count = new_count
            review.consecutive_correct = new_consecutive
            review.interval_days = new_interval
            review.priority = new_priority
            review.due_date = new_due_date
            review.last_reviewed_at = datetime.now(UTC)
            await self._session.flush()

        return await self._reviews.get_with_question(review.id)

    async def skip_review(
        self,
        review_id: uuid.UUID,
        user_id: uuid.UUID,
        skip_until: date | None = None,
    ) -> Review:
        """Pula uma revisão, reagendando para o futuro."""

        review = await self.get_review(review_id, user_id)

        if review.status != ReviewStatus.PENDENTE:
            raise ConflictError("Esta revisão já foi concluída ou pulada.")

        # Define nova data
        if skip_until:
            new_due_date = skip_until
        else:
            new_due_date = date.today() + timedelta(days=1)

        # Aumenta prioridade se pular
        new_priority = (
            ReviewPriority.ALTA
            if review.priority == ReviewPriority.MEDIA
            else ReviewPriority.ALTA
        )

        async with UnitOfWork(self._session):
            review.status = ReviewStatus.PULAR
            review.due_date = new_due_date
            review.priority = new_priority
            await self._session.flush()

        return await self._reviews.get_with_question(review.id)

    # ==================================================================== #
    # AGENDAMENTO AUTOMÁTICO
    # ==================================================================== #

    async def auto_schedule_from_errors(self, user_id: uuid.UUID) -> list[Review]:
        """Agenda revisões automaticamente a partir de questões erradas."""

        from app.models.practice.question_attempt import QuestionAttempt
        from sqlalchemy import select, func

        seven_days_ago = datetime.now(UTC) - timedelta(days=7)
        stmt = (
            select(QuestionAttempt.question_id)
            .where(
                QuestionAttempt.user_id == user_id,
                QuestionAttempt.is_correct.is_(False),
                QuestionAttempt.answered_at >= seven_days_ago,
            )
            .group_by(QuestionAttempt.question_id)
            .order_by(func.count().desc())
            .limit(20)
        )
        result = await self._session.execute(stmt)
        question_ids = [row[0] for row in result.all()]

        if not question_ids:
            return []

        # Filtrar questões que já têm revisão pendente
        due_reviews = await self._reviews.list_due(user_id)
        existing_question_ids = {r.question_id for r in due_reviews}
        new_question_ids = [qid for qid in question_ids if qid not in existing_question_ids]

        if not new_question_ids:
            return []

        return await self.schedule_batch(
            user_id=user_id,
            question_ids=new_question_ids,
            priority=ReviewPriority.ALTA,
        )