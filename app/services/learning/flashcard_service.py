"""Regras de negócio de flashcards: CRUD, revisão espaçada (SM-2) e
criação automática a partir de questões já respondidas.
"""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationDomainError
from app.database.uow import UnitOfWork
from app.models.content.question import Question
from app.models.enums import FlashcardGrade
from app.models.learning.flashcard import Flashcard
from app.models.learning.flashcard_review import FlashcardReview
from app.repositories.content.question_repository import QuestionRepository
from app.repositories.content.taxonomy_repository import DisciplineRepository
from app.repositories.learning.flashcard_repository import (
    FlashcardFilters,
    FlashcardRepository,
    FlashcardReviewRepository,
)
from app.schemas.learning.flashcard import (
    FlashcardCreateFromQuestionRequest,
    FlashcardCreateRequest,
    FlashcardDisciplineStats,
    FlashcardStatsResponse,
    FlashcardUpdateRequest,
)
from app.services.learning.sm2 import DEFAULT_EASINESS_FACTOR, SM2State, sm2


class FlashcardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._flashcards = FlashcardRepository(session)
        self._reviews = FlashcardReviewRepository(session)
        self._disciplines = DisciplineRepository(session)
        self._questions = QuestionRepository(session)

    # ------------------------------------------------------------------ #
    # Leitura
    # ------------------------------------------------------------------ #

    async def get_flashcard(self, flashcard_id: uuid.UUID, user_id: uuid.UUID) -> Flashcard:
        flashcard = await self._flashcards.get_owned(flashcard_id, user_id)
        if flashcard is None:
            raise NotFoundError("Flashcard não encontrado.")
        return flashcard

    async def list_flashcards(
        self, limit: int, cursor_id: uuid.UUID | None, filters: FlashcardFilters
    ) -> list[Flashcard]:
        return await self._flashcards.list_paginated(limit=limit, cursor_id=cursor_id, filters=filters)

    async def list_due(self, user_id: uuid.UUID, limit: int = 200) -> list[Flashcard]:
        return await self._flashcards.list_due(user_id, limit=limit)

    async def list_by_user(self, user_id: uuid.UUID) -> list[Flashcard]:
        return await self._flashcards.list_by_user(user_id)

    async def list_by_question(self, question_id: uuid.UUID, user_id: uuid.UUID) -> list[Flashcard]:
        return await self._flashcards.list_by_question(question_id, user_id)

    async def list_by_discipline(self, discipline_id: uuid.UUID, user_id: uuid.UUID) -> list[Flashcard]:
        return await self._flashcards.list_by_discipline(discipline_id, user_id)

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #

    async def create_flashcard(self, user_id: uuid.UUID, data: FlashcardCreateRequest) -> Flashcard:
        if data.discipline_id is not None:
            if await self._disciplines.get_by_id(data.discipline_id) is None:
                raise NotFoundError("Disciplina não encontrada.")

        question: Question | None = None
        if data.question_id is not None:
            question = await self._questions.get_with_relations(data.question_id)
            if question is None:
                raise NotFoundError("Questão não encontrada.")

        flashcard = Flashcard(
            user_id=user_id,
            question_id=data.question_id,
            discipline_id=data.discipline_id or (question.discipline_id if question else None),
            front=data.front,
            back=data.back,
        )

        async with UnitOfWork(self._session):
            await self._flashcards.add(flashcard)
            self._session.add(_new_review_state(flashcard.id, user_id))

        return await self.get_flashcard(flashcard.id, user_id)

    async def create_from_question(
        self, user_id: uuid.UUID, data: FlashcardCreateFromQuestionRequest
    ) -> Flashcard:
        """Cria um flashcard a partir de uma questão já respondida.

        Quando `front`/`back` não são enviados, monta o cartão a partir do
        enunciado (frente) e do gabarito comentado (verso) da questão.
        """
        question = await self._questions.get_with_relations(data.question_id)
        if question is None:
            raise NotFoundError("Questão não encontrada.")

        front = data.front or question.statement
        back = data.back or _default_back_from_question(question)

        flashcard = Flashcard(
            user_id=user_id,
            question_id=question.id,
            discipline_id=question.discipline_id,
            front=front,
            back=back,
        )

        async with UnitOfWork(self._session):
            await self._flashcards.add(flashcard)
            self._session.add(_new_review_state(flashcard.id, user_id))

        return await self.get_flashcard(flashcard.id, user_id)

    async def update_flashcard(
        self, flashcard_id: uuid.UUID, user_id: uuid.UUID, data: FlashcardUpdateRequest
    ) -> Flashcard:
        flashcard = await self.get_flashcard(flashcard_id, user_id)

        fields = data.model_dump(exclude_unset=True)
        if "discipline_id" in fields and fields["discipline_id"] is not None:
            if await self._disciplines.get_by_id(fields["discipline_id"]) is None:
                raise NotFoundError("Disciplina não encontrada.")

        async with UnitOfWork(self._session):
            for field, value in fields.items():
                setattr(flashcard, field, value)
            await self._session.flush()

        return await self.get_flashcard(flashcard.id, user_id)

    async def delete_flashcard(self, flashcard_id: uuid.UUID, user_id: uuid.UUID) -> None:
        flashcard = await self.get_flashcard(flashcard_id, user_id)
        async with UnitOfWork(self._session):
            await self._flashcards.delete(flashcard)

    # ------------------------------------------------------------------ #
    # Revisão espaçada (SM-2)
    # ------------------------------------------------------------------ #

    async def review_flashcard(
        self, flashcard_id: uuid.UUID, user_id: uuid.UUID, grade: FlashcardGrade
    ) -> Flashcard:
        flashcard = await self.get_flashcard(flashcard_id, user_id)
        review = flashcard.review_state
        if review is None:
            raise ValidationDomainError("Flashcard sem estado de revisão inicializado.")

        current_state = SM2State(
            easiness_factor=review.easiness_factor,
            interval_days=review.interval_days,
            repetitions=review.repetitions,
        )
        result = sm2(current_state, grade)

        async with UnitOfWork(self._session):
            review.easiness_factor = result.easiness_factor
            review.interval_days = result.interval_days
            review.repetitions = result.repetitions
            review.due_date = result.due_date
            review.last_reviewed_at = _utcnow()
            review.last_grade = grade
            await self._session.flush()

        return await self.get_flashcard(flashcard.id, user_id)

    # ------------------------------------------------------------------ #
    # Estatísticas
    # ------------------------------------------------------------------ #

    async def get_stats(self, user_id: uuid.UUID) -> FlashcardStatsResponse:
        total = await self._flashcards.count_by_user(user_id)
        due_today = await self._flashcards.count_due(user_id)
        reviewed_today = await self._reviews.count_reviewed_today(user_id)
        reviewed_total = await self._reviews.count_reviewed_total(user_id)
        grade_counts_today = await self._reviews.count_by_grade_today(user_id)

        graded_today = sum(grade_counts_today.values())
        known_today = grade_counts_today.get(FlashcardGrade.BOM.value, 0) + grade_counts_today.get(
            FlashcardGrade.FACIL.value, 0
        )
        retention_rate = round((known_today / graded_today) * 100, 1) if graded_today else 0.0

        by_discipline = await self._stats_by_discipline(user_id)

        return FlashcardStatsResponse(
            total=total,
            due_today=due_today,
            reviewed_today=reviewed_today,
            reviewed_total=reviewed_total,
            retention_rate=retention_rate,
            streak_days=await self._streak_days(user_id),
            by_discipline=by_discipline,
        )

    async def _stats_by_discipline(self, user_id: uuid.UUID) -> list[FlashcardDisciplineStats]:
        flashcards = await self._flashcards.list_by_user(user_id)
        grouped: dict[uuid.UUID | None, dict[str, object]] = {}
        for card in flashcards:
            key = card.discipline_id
            bucket = grouped.setdefault(
                key,
                {
                    "name": card.discipline.name if card.discipline else "Sem disciplina",
                    "total": 0,
                    "due_today": 0,
                },
            )
            bucket["total"] = int(bucket["total"]) + 1
            if card.review_state and card.review_state.due_date <= date.today():
                bucket["due_today"] = int(bucket["due_today"]) + 1

        return [
            FlashcardDisciplineStats(
                discipline_id=discipline_id,
                discipline_name=str(bucket["name"]),
                total=int(bucket["total"]),
                due_today=int(bucket["due_today"]),
            )
            for discipline_id, bucket in grouped.items()
        ]

    async def _streak_days(self, user_id: uuid.UUID) -> int:
        """Dias consecutivos (incluindo hoje ou ontem) com pelo menos uma revisão.

        Antes desta correção, o método era um placeholder que só retornava
        0 ou 1 (nunca refletia sequências reais de vários dias). A sequência
        de estudos "de verdade" já existe no módulo de analytics
        (`StudyStreak`/`_recompute_streaks`), mas ela é alimentada só por
        `user_daily_stats.questions_answered` — ou seja, por questões
        respondidas, não por revisões de flashcard. Reaproveitar aquele
        streak aqui faria o streak de flashcards ficar zerado para quem só
        estuda por flashcard, o que seria pior que o bug atual.

        Por isso o cálculo é feito aqui, no próprio contexto de
        aprendizagem, com a mesma lógica de sequência consecutiva usada em
        `_recompute_streaks` (analytics), mas a partir das datas reais de
        `flashcard_reviews.last_reviewed_at`.
        """
        review_dates = await self._reviews.list_review_dates(user_id)
        if not review_dates:
            return 0

        current_run = 1
        for previous, current in zip(review_dates, review_dates[1:]):
            current_run = current_run + 1 if (current - previous).days == 1 else 1

        last_date = review_dates[-1]
        today = date.today()
        return current_run if (today - last_date).days <= 1 else 0


def _new_review_state(flashcard_id: uuid.UUID, user_id: uuid.UUID) -> FlashcardReview:
    """Estado inicial de um flashcard recém-criado: pronto para revisar hoje."""
    return FlashcardReview(
        flashcard_id=flashcard_id,
        user_id=user_id,
        easiness_factor=DEFAULT_EASINESS_FACTOR,
        interval_days=0,
        repetitions=0,
        due_date=date.today(),
    )


def _default_back_from_question(question: Question) -> str:
    correct = next(
        (alt for alt in question.alternatives if alt.letter == question.correct_alternative_letter),
        None,
    )
    parts = [f"Alternativa correta ({question.correct_alternative_letter}): {correct.text if correct else ''}"]
    if question.explanation:
        parts.append(question.explanation)
    return "\n\n".join(parts)


def _utcnow():
    from datetime import UTC, datetime

    return datetime.now(UTC)