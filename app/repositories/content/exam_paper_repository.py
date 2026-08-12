"""Repositório de acesso a dados de `ExamPaper`."""

import uuid
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.models.content.exam_paper import ExamPaper, ExamPaperQuestion
from app.repositories.base import BaseRepository

_RELATIONS = (
    selectinload(ExamPaper.exam_board),
    selectinload(ExamPaper.organization),
)


class ExamPaperRepository(BaseRepository[ExamPaper]):
    model = ExamPaper

    async def get_with_relations(self, paper_id: uuid.UUID) -> ExamPaper | None:
        """Busca prova com todas as relações carregadas."""
        stmt = (
            select(ExamPaper)
            .where(ExamPaper.id == paper_id, ExamPaper.is_active.is_(True))
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_questions(self, paper_id: uuid.UUID) -> ExamPaper | None:
        """Busca prova com as questões carregadas."""
        stmt = (
            select(ExamPaper)
            .where(ExamPaper.id == paper_id, ExamPaper.is_active.is_(True))
            .options(
                *_RELATIONS,
                selectinload(ExamPaper.questions).selectinload(ExamPaperQuestion.question)
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        limit: int = 20,
        cursor_id: Optional[uuid.UUID] = None,
        exam_board_id: Optional[uuid.UUID] = None,
        organization_id: Optional[uuid.UUID] = None,
        year: Optional[int] = None,
        search: Optional[str] = None,
    ) -> list[ExamPaper]:
        """Lista provas paginadas com filtros."""
        stmt = select(ExamPaper).where(ExamPaper.is_active.is_(True))

        if exam_board_id:
            stmt = stmt.where(ExamPaper.exam_board_id == exam_board_id)
        if organization_id:
            stmt = stmt.where(ExamPaper.organization_id == organization_id)
        if year:
            stmt = stmt.where(ExamPaper.year == year)
        if search:
            stmt = stmt.where(
                or_(
                    ExamPaper.title.ilike(f"%{search}%"),
                    ExamPaper.description.ilike(f"%{search}%"),
                )
            )

        stmt = stmt.options(*_RELATIONS).order_by(
            ExamPaper.year.desc(),
            ExamPaper.created_at.desc(),
        ).limit(limit)

        if cursor_id:
            cursor = await self.get_by_id(cursor_id)
            if cursor:
                stmt = stmt.where(
                    (ExamPaper.year < cursor.year) | 
                    ((ExamPaper.year == cursor.year) & (ExamPaper.created_at < cursor.created_at))
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_years(self) -> list[int]:
        """Lista anos disponíveis nas provas."""
        stmt = select(ExamPaper.year).where(ExamPaper.is_active.is_(True)).distinct().order_by(ExamPaper.year.desc())
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def count_by_filters(
        self,
        exam_board_id: Optional[uuid.UUID] = None,
        organization_id: Optional[uuid.UUID] = None,
        year: Optional[int] = None,
    ) -> int:
        """Conta provas com os filtros aplicados."""
        stmt = select(ExamPaper).where(ExamPaper.is_active.is_(True))
        if exam_board_id:
            stmt = stmt.where(ExamPaper.exam_board_id == exam_board_id)
        if organization_id:
            stmt = stmt.where(ExamPaper.organization_id == organization_id)
        if year:
            stmt = stmt.where(ExamPaper.year == year)
        
        result = await self.session.execute(stmt)
        return len(result.scalars().all())