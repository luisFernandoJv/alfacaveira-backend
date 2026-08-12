"""Schemas de request/response de provas anteriores."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.content.exam_source import ExamBoardResponse, OrganizationResponse
from app.schemas.content.question import QuestionListItem


class ExamPaperResponse(BaseModel):
    """Resposta de uma prova (metadados)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    exam_board: ExamBoardResponse
    organization: OrganizationResponse
    year: int
    total_questions: int
    pdf_url: str | None
    created_at: datetime
    updated_at: datetime


class ExamPaperDetailResponse(ExamPaperResponse):
    """Resposta detalhada de uma prova (com questões)."""

    questions: list[QuestionListItem]


class ExamPaperListResponse(BaseModel):
    """Resposta paginada de provas."""

    items: list[ExamPaperResponse]
    total: int
    next_cursor: str | None = None
    has_more: bool = False


class ExamPaperStatsResponse(BaseModel):
    """Estatísticas do catálogo de provas."""

    total: int
    by_board: dict[str, int]
    by_year: dict[int, int]
    latest: list[dict]


class ExamPaperFilters(BaseModel):
    """Filtros para listagem de provas."""

    exam_board_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    search: str | None = Field(default=None, max_length=200)