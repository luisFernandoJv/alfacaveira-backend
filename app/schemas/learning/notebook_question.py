# app/schemas/learning/notebook_question.py
"""Schemas de request/response de questões em cadernos."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import MAX_BULK_QUESTION_SELECTION
from app.schemas.content.question import QuestionListItem


class NotebookQuestionResponse(BaseModel):
    """Resposta de uma questão em um caderno."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    notebook_id: uuid.UUID
    question_id: uuid.UUID
    added_at: datetime
    question: QuestionListItem


class NotebookQuestionAddRequest(BaseModel):
    """Request para adicionar uma questão ao caderno."""

    question_id: uuid.UUID


class NotebookQuestionBulkAddRequest(BaseModel):
    """Request para adicionar múltiplas questões ao caderno."""

    question_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=MAX_BULK_QUESTION_SELECTION
    )


class NotebookQuestionListResponse(BaseModel):
    """Lista de questões de um caderno."""

    items: list[NotebookQuestionResponse]
    total: int
    next_cursor: str | None = None
    has_more: bool = False


class NotebookQuestionMoveRequest(BaseModel):
    """Request para mover questões entre cadernos."""

    target_notebook_id: uuid.UUID
    question_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=MAX_BULK_QUESTION_SELECTION
    )


class NotebookQuestionCopyRequest(BaseModel):
    """Request para copiar questões entre cadernos."""

    target_notebook_id: uuid.UUID
    question_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=MAX_BULK_QUESTION_SELECTION
    )