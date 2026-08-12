"""Regras de negócio de provas anteriores."""

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.content.exam_paper import ExamPaper
from app.repositories.content.exam_paper_repository import ExamPaperRepository


class ExamPaperService:
    """Serviço de provas anteriores."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._papers = ExamPaperRepository(session)

    async def get_paper(self, paper_id: uuid.UUID) -> ExamPaper:
        """Busca uma prova pelo ID."""
        paper = await self._papers.get_with_questions(paper_id)
        if paper is None:
            raise NotFoundError("Prova não encontrada.")
        return paper

    async def get_paper_metadata(self, paper_id: uuid.UUID) -> ExamPaper:
        """Busca apenas os metadados da prova (sem questões)."""
        paper = await self._papers.get_with_relations(paper_id)
        if paper is None:
            raise NotFoundError("Prova não encontrada.")
        return paper

    async def list_papers(
        self,
        limit: int = 20,
        cursor_id: Optional[uuid.UUID] = None,
        exam_board_id: Optional[uuid.UUID] = None,
        organization_id: Optional[uuid.UUID] = None,
        year: Optional[int] = None,
        search: Optional[str] = None,
    ) -> list[ExamPaper]:
        """Lista provas com filtros."""
        return await self._papers.list_paginated(
            limit=limit,
            cursor_id=cursor_id,
            exam_board_id=exam_board_id,
            organization_id=organization_id,
            year=year,
            search=search,
        )

    async def list_years(self) -> list[int]:
        """Lista anos disponíveis."""
        return await self._papers.list_years()

    async def get_stats(self) -> dict:
        """Estatísticas do catálogo de provas."""
        all_papers = await self._papers.list_paginated(limit=1000)
        total = len(all_papers)
        
        # Agrupar por banca
        by_board = {}
        for paper in all_papers:
            board_name = paper.exam_board.name if paper.exam_board else "Sem banca"
            by_board[board_name] = by_board.get(board_name, 0) + 1

        # Agrupar por ano
        by_year = {}
        for paper in all_papers:
            by_year[paper.year] = by_year.get(paper.year, 0) + 1

        # Últimas provas
        latest = sorted(all_papers, key=lambda p: p.year, reverse=True)[:5]

        return {
            "total": total,
            "by_board": by_board,
            "by_year": by_year,
            "latest": [
                {
                    "id": str(p.id),
                    "title": p.title,
                    "year": p.year,
                    "exam_board": p.exam_board.name if p.exam_board else None,
                }
                for p in latest
            ],
        }