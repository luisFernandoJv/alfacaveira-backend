"""Repositório de acesso a dados de `Question`.

Listagem pública filtrável + busca full-text, paginação cursor-based (mesmo
padrão de `UserRepository.list_paginated`, Etapa 6) e carregamento antecipado
(`selectinload`) das relações usadas pelos schemas de resposta, para evitar
N+1 nas listagens.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.models.content.question import Question
from app.models.enums import QuestionDifficulty, QuestionStatus
from app.repositories.base import BaseRepository

_RELATIONS = (
    selectinload(Question.discipline),
    selectinload(Question.subject),
    selectinload(Question.topic),
    selectinload(Question.exam_board),
    selectinload(Question.exam_edition),
    selectinload(Question.organization),
    selectinload(Question.alternatives),
    selectinload(Question.tags),
)


@dataclass
class QuestionFilters:
    """Filtros da listagem pública, todos opcionais (combinados com AND)."""

    discipline_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    exam_board_id: uuid.UUID | None = None
    exam_edition_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    year: int | None = None
    difficulty: QuestionDifficulty | None = None
    status: QuestionStatus | None = None
    tag_id: uuid.UUID | None = None
    search: str | None = None


class QuestionRepository(BaseRepository[Question]):
    model = Question

    def _apply_filters(
        self, stmt: Select[tuple[Question]], filters: QuestionFilters
    ) -> Select[tuple[Question]]:
        if filters.discipline_id is not None:
            stmt = stmt.where(Question.discipline_id == filters.discipline_id)
        if filters.subject_id is not None:
            stmt = stmt.where(Question.subject_id == filters.subject_id)
        if filters.topic_id is not None:
            stmt = stmt.where(Question.topic_id == filters.topic_id)
        if filters.exam_board_id is not None:
            stmt = stmt.where(Question.exam_board_id == filters.exam_board_id)
        if filters.exam_edition_id is not None:
            stmt = stmt.where(Question.exam_edition_id == filters.exam_edition_id)
        if filters.organization_id is not None:
            stmt = stmt.where(Question.organization_id == filters.organization_id)
        if filters.year is not None:
            stmt = stmt.where(Question.year == filters.year)
        if filters.difficulty is not None:
            stmt = stmt.where(Question.difficulty == filters.difficulty)
        if filters.status is not None:
            stmt = stmt.where(Question.status == filters.status)
        if filters.tag_id is not None:
            stmt = stmt.where(Question.tags.any(id=filters.tag_id))
        if filters.search:
            # `search_vector` é mantido por trigger (to_tsvector('portuguese', ...)),
            # então a query também precisa ser 'portuguese' para casar os lexemas.
            stmt = stmt.where(
                Question.search_vector.op("@@")(func.plainto_tsquery("portuguese", filters.search))
            )
        return stmt

    async def get_with_relations(self, question_id: uuid.UUID) -> Question | None:
        stmt = select(Question).where(Question.id == question_id).options(*_RELATIONS)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_ids(self, question_ids: list[uuid.UUID]) -> list[Question]:
        """Busca por lote de IDs, com relações carregadas.

        Reutilizado por `practice` para montar as questões de uma sessão de
        treino sem precisar de N+1 (uma questão por vez).
        """
        if not question_ids:
            return []
        stmt = select(Question).where(Question.id.in_(question_ids)).options(*_RELATIONS)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_random(self, filters: QuestionFilters, limit: int) -> list[Question]:
        """Seleciona até `limit` questões aleatórias que casam com os filtros.

        Usado para montar uma sessão de treino a partir de um conjunto de
        filtros. `ORDER BY random()` é aceitável no volume atual (milhares de
        questões); se a tabela crescer para a casa de milhões, revisitar com
        uma estratégia de amostragem mais barata (ex.: TABLESAMPLE).
        """
        stmt = select(Question).options(*_RELATIONS).order_by(func.random()).limit(limit)
        stmt = self._apply_filters(stmt, filters)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_paginated(
        self, limit: int, cursor_id: uuid.UUID | None, filters: QuestionFilters
    ) -> list[Question]:
        """Listagem paginada por keyset (created_at, id), com filtros e busca full-text."""
        stmt = (
            select(Question)
            .options(*_RELATIONS)
            .order_by(Question.created_at.asc(), Question.id.asc())
            .limit(limit)
        )
        stmt = self._apply_filters(stmt, filters)

        if cursor_id is not None:
            cursor_question = await self.get_by_id(cursor_id)
            if cursor_question is not None:
                stmt = stmt.where(
                    (Question.created_at > cursor_question.created_at)
                    | (
                        (Question.created_at == cursor_question.created_at)
                        & (Question.id > cursor_question.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())
