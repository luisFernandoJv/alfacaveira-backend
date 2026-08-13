# app/schemas/learning/notebook_tag.py
"""Schemas de request/response de tags de cadernos."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotebookTagResponse(BaseModel):
    """Resposta de uma tag."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class NotebookTagCreateRequest(BaseModel):
    """Request para criar uma tag."""

    name: str = Field(min_length=1, max_length=80)


class NotebookTagListResponse(BaseModel):
    """Lista de tags."""

    items: list[NotebookTagResponse]
    total: int