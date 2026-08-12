# app/schemas/content/notebook.py
"""Schemas de request/response de cadernos (notebooks)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.content.question import QuestionListItem


# ============================================================================
# FOLDERS
# ============================================================================

class NotebookFolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


# ============================================================================
# TAGS
# ============================================================================

class NotebookTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


# ============================================================================
# QUESTIONS
# ============================================================================

class NotebookQuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    question: QuestionListItem
    note: str | None
    added_at: datetime


# ============================================================================
# NOTEBOOKS
# ============================================================================

class NotebookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    is_favorite: bool
    folder_id: uuid.UUID | None
    folder: NotebookFolderResponse | None = None
    tags: list[NotebookTagResponse] = Field(default_factory=list)
    questions: list[NotebookQuestionResponse] = Field(default_factory=list)
    question_count: int = Field(default=0)
    created_at: datetime
    updated_at: datetime


class NotebookCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    folder_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list)


class NotebookUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    is_favorite: bool | None = None
    folder_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] | None = None


class NotebookAddQuestionRequest(BaseModel):
    question_id: uuid.UUID = Field(description="ID da questão a ser adicionada")
    note: str | None = Field(default=None, max_length=5000, description="Anotação opcional")


class NotebookListResponse(BaseModel):
    items: list[NotebookResponse]
    total: int
    next_cursor: str | None = None
    has_more: bool = False