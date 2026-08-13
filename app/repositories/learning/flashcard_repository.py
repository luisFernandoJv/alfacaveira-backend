"""Repositório de acesso a dados de `Flashcard` (+ estado de revisão SM-2).

Segue o mesmo padrão de `QuestionRepository`: filtros combináveis via
dataclass, paginação cursor-based (created_at, id) e `selectinload` das
relações usadas pelos schemas de resposta, para evitar N+1 nas listagens.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.models.learning.flashcard import Flashcard
from app.models.learning.flashcard_review import FlashcardReview
from app.repositories.base import BaseRepository

_RELATIONS = (
    selectinload(Flashcard.review_state),
    selectinload(Flashcard.discipline),
)


@dataclass
class FlashcardFilters:
    """Filtros da listagem de flashcards do usuário, combinados com AND."""

    user_id: uuid.UUID
    discipline_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    due_only: bool = False
    search: str | None = None


class FlashcardRepository(BaseRepository[Flashcard]):
    model = Flashcard

    def _apply_filters(
        self, stmt: Select[tuple[Flashcard]], filters: FlashcardFilters
    ) -> Select[tuple[Flashcard]]:
        stmt = stmt.where(Flashcard.user_id == filters.user_id)
        if filters.discipline_id is not None:
            stmt = stmt.where(Flashcard.discipline_id == filters.discipline_id)
        if filters.question_id is not None:
            stmt = stmt.where(Flashcard.question_id == filters.question_id)
        if filters.search:
            like = f"%{filters.search}%"
            stmt = stmt.where((Flashcard.front.ilike(like)) | (Flashcard.back.ilike(like)))
        if filters.due_only:
            stmt = stmt.join(FlashcardReview).where(FlashcardReview.due_date <= date.today())
        return stmt

    async def get_with_relations(self, flashcard_id: uuid.UUID) -> Flashcard | None:
        stmt = select(Flashcard).where(Flashcard.id == flashcard_id).options(*_RELATIONS)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned(self, flashcard_id: uuid.UUID, user_id: uuid.UUID) -> Flashcard | None:
        """Busca por id, restrita ao dono — usada antes de update/delete/review."""
        stmt = (
            select(Flashcard)
            .where(Flashcard.id == flashcard_id, Flashcard.user_id == user_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self, limit: int, cursor_id: uuid.UUID | None, filters: FlashcardFilters
    ) -> list[Flashcard]:
        """Listagem paginada por keyset (created_at, id), com filtros e busca."""
        stmt = (
            select(Flashcard)
            .options(*_RELATIONS)
            .order_by(Flashcard.created_at.asc(), Flashcard.id.asc())
            .limit(limit)
        )
        stmt = self._apply_filters(stmt, filters)

        if cursor_id is not None:
            cursor_flashcard = await self.get_by_id(cursor_id)
            if cursor_flashcard is not None:
                stmt = stmt.where(
                    (Flashcard.created_at > cursor_flashcard.created_at)
                    | (
                        (Flashcard.created_at == cursor_flashcard.created_at)
                        & (Flashcard.id > cursor_flashcard.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_due(self, user_id: uuid.UUID, limit: int = 200) -> list[Flashcard]:
        """Flashcards pendentes de revisão hoje (`due_date <= hoje`), mais antigos primeiro."""
        stmt = (
            select(Flashcard)
            .join(FlashcardReview)
            .where(Flashcard.user_id == user_id, FlashcardReview.due_date <= date.today())
            .options(*_RELATIONS)
            .order_by(FlashcardReview.due_date.asc(), Flashcard.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_by_user(self, user_id: uuid.UUID) -> list[Flashcard]:
        stmt = (
            select(Flashcard)
            .where(Flashcard.user_id == user_id)
            .options(*_RELATIONS)
            .order_by(Flashcard.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_by_question(self, question_id: uuid.UUID, user_id: uuid.UUID) -> list[Flashcard]:
        stmt = (
            select(Flashcard)
            .where(Flashcard.question_id == question_id, Flashcard.user_id == user_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_by_discipline(self, discipline_id: uuid.UUID, user_id: uuid.UUID) -> list[Flashcard]:
        stmt = (
            select(Flashcard)
            .where(Flashcard.discipline_id == discipline_id, Flashcard.user_id == user_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def count_by_user(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Flashcard).where(Flashcard.user_id == user_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_due(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Flashcard)
            .join(FlashcardReview)
            .where(Flashcard.user_id == user_id, FlashcardReview.due_date <= date.today())
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def delete(self, flashcard: Flashcard) -> None:
        await self.session.delete(flashcard)
        await self.session.flush()


class FlashcardReviewRepository(BaseRepository[FlashcardReview]):
    model = FlashcardReview

    async def get_by_flashcard_id(self, flashcard_id: uuid.UUID) -> FlashcardReview | None:
        stmt = select(FlashcardReview).where(FlashcardReview.flashcard_id == flashcard_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_reviewed_today(self, user_id: uuid.UUID) -> int:
        """Quantos flashcards distintos o usuário já revisou hoje."""
        stmt = (
            select(func.count())
            .select_from(FlashcardReview)
            .where(
                FlashcardReview.user_id == user_id,
                func.date(FlashcardReview.last_reviewed_at) == date.today(),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_reviewed_total(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(FlashcardReview)
            .where(FlashcardReview.user_id == user_id, FlashcardReview.repetitions > 0)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_by_grade_today(self, user_id: uuid.UUID) -> dict[str, int]:
        """Distribuição de notas dadas hoje, para cálculo de retenção."""
        stmt = (
            select(FlashcardReview.last_grade, func.count())
            .where(
                FlashcardReview.user_id == user_id,
                func.date(FlashcardReview.last_reviewed_at) == date.today(),
            )
            .group_by(FlashcardReview.last_grade)
        )
        result = await self.session.execute(stmt)
        return {str(grade): count for grade, count in result.all() if grade is not None}

    async def list_review_dates(self, user_id: uuid.UUID) -> list[date]:
        """Datas distintas (mais antiga → mais recente) em que o usuário revisou
        ao menos um flashcard.

        Fonte de dados para o cálculo do streak de flashcards em
        `FlashcardService._streak_days`. Mesma ideia do worker de analytics
        (`_recompute_streaks`), mas escopada ao contexto de aprendizagem —
        não depende de `user_daily_stats`, que hoje só agrega questões
        respondidas e não enxerga revisões de flashcard.
        """
        stmt = (
            select(func.date(FlashcardReview.last_reviewed_at))
            .where(
                FlashcardReview.user_id == user_id,
                FlashcardReview.last_reviewed_at.is_not(None),
            )
            .distinct()
            .order_by(func.date(FlashcardReview.last_reviewed_at))
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]