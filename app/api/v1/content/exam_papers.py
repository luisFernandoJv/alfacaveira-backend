"""Endpoints HTTP de provas anteriores."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.schemas.content.exam_paper import (
    ExamPaperDetailResponse,
    ExamPaperResponse,
    ExamPaperStatsResponse,
)
from app.security.dependencies import CurrentUser
from app.services.content.exam_paper_service import ExamPaperService

router = APIRouter()


def get_exam_paper_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExamPaperService:
    return ExamPaperService(session)


ExamPaperServiceDep = Annotated[ExamPaperService, Depends(get_exam_paper_service)]


@router.get("", response_model=Envelope[list[ExamPaperResponse]])
async def list_exam_papers(
    current_user: CurrentUser,
    exam_paper_service: ExamPaperServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    exam_board_id: Annotated[uuid.UUID | None, Query()] = None,
    organization_id: Annotated[uuid.UUID | None, Query()] = None,
    year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Envelope[list[ExamPaperResponse]]:
    """Lista provas anteriores com filtros."""
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    papers = await exam_paper_service.list_papers(
        limit=limit,
        cursor_id=cursor_id,
        exam_board_id=exam_board_id,
        organization_id=organization_id,
        year=year,
        search=search,
    )

    next_cursor = (
        CursorPage.encode_cursor(str(papers[-1].id)) if len(papers) == limit else None
    )

    return Envelope(
        data=[ExamPaperResponse.model_validate(p) for p in papers],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )


@router.get("/stats", response_model=Envelope[ExamPaperStatsResponse])
async def get_exam_paper_stats(
    current_user: CurrentUser,
    exam_paper_service: ExamPaperServiceDep,
) -> Envelope[ExamPaperStatsResponse]:
    """Estatísticas do catálogo de provas."""
    stats = await exam_paper_service.get_stats()
    return Envelope(data=ExamPaperStatsResponse.model_validate(stats))


@router.get("/years", response_model=Envelope[list[int]])
async def list_exam_paper_years(
    current_user: CurrentUser,
    exam_paper_service: ExamPaperServiceDep,
) -> Envelope[list[int]]:
    """Lista anos disponíveis nas provas."""
    years = await exam_paper_service.list_years()
    return Envelope(data=years)


@router.get("/{paper_id}", response_model=Envelope[ExamPaperDetailResponse])
async def get_exam_paper(
    paper_id: uuid.UUID,
    current_user: CurrentUser,
    exam_paper_service: ExamPaperServiceDep,
) -> Envelope[ExamPaperDetailResponse]:
    """Detalhe de uma prova com questões."""
    paper = await exam_paper_service.get_paper(paper_id)
    return Envelope(data=ExamPaperDetailResponse.model_validate(paper))