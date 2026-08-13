# app/schemas/learning/notebook_folder.py
"""Schemas de request/response de pastas de cadernos."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotebookFolderResponse(BaseModel):
    """Resposta de uma pasta de caderno."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class NotebookFolderCreateRequest(BaseModel):
    """Request para criar uma pasta."""

    name: str = Field(min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None


class NotebookFolderUpdateRequest(BaseModel):
    """Request para atualizar uma pasta."""

    name: str = Field(min_length=1, max_length=255)


class NotebookFolderListResponse(BaseModel):
    """Lista de pastas do usuário."""

    items: list[NotebookFolderResponse]
    total: int