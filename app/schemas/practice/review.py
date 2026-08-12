"""Schemas de request/response de revisões espaçadas."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReviewPriority, ReviewStatus
from app.schemas.content.question import QuestionListItem


class ReviewResponse(BaseModel):
    """Resposta de uma revisão."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    status: ReviewStatus
    priority: ReviewPriority
    due_date: date
    last_reviewed_at: datetime | None
    review_count: int
    consecutive_correct: int
    interval_days: int
    question: QuestionListItem


class ReviewListResponse(BaseModel):
    """Lista de revisões com metadados."""

    items: list[ReviewResponse]
    total: int
    due_today: int
    next_due_date: date | None


class ReviewStartRequest(BaseModel):
    """Iniciar uma revisão."""

    review_id: uuid.UUID


class ReviewCompleteRequest(BaseModel):
    """Concluir uma revisão."""

    review_id: uuid.UUID
    is_correct: bool
    time_spent_seconds: int | None = Field(default=None, ge=0)


class ReviewSkipRequest(BaseModel):
    """Pular uma revisão."""

    review_id: uuid.UUID
    skip_until: date | None = None


class ReviewStatsResponse(BaseModel):
    """Estatísticas de revisão do usuário."""

    total_due: int
    due_today: int
    overdue: int
    completed_today: int
    completion_rate: float
    average_interval: float
    longest_streak: int