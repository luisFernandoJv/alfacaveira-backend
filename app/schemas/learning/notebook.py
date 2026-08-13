# app/schemas/learning/notebook.py
"""Schemas de request/response de cadernos."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.schemas.content.question import QuestionListItem
from app.schemas.learning.notebook_folder import NotebookFolderResponse
from app.schemas.learning.notebook_tag import NotebookTagResponse


class NotebookResponse(BaseModel):
    """Resposta de um caderno (metadados)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    folder_id: uuid.UUID | None
    folder: NotebookFolderResponse | None
    is_favorite: bool
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def question_count(self) -> int:
        """Número de questões no caderno."""
        # Se o objeto tiver a lista de questions carregada, usa ela
        if hasattr(self, 'questions') and self.questions is not None:
            return len(self.questions)
        # Caso contrário, tenta usar o atributo que pode ter sido definido
        if hasattr(self, '_question_count'):
            return self._question_count
        return 0


class NotebookDetailResponse(NotebookResponse):
    """Resposta detalhada de um caderno (com questões)."""

    questions: list[QuestionListItem] = Field(default_factory=list)


class NotebookCreateRequest(BaseModel):
    """Request para criar um caderno."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    folder_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list)


class NotebookUpdateRequest(BaseModel):
    """Request para atualizar um caderno."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    folder_id: uuid.UUID | None = None
    is_favorite: bool | None = None
    tag_ids: list[uuid.UUID] | None = None


class NotebookListResponse(BaseModel):
    """Lista de cadernos do usuário."""

    items: list[NotebookResponse]
    total: int
    next_cursor: str | None = None
    has_more: bool = False


class NotebookFavoriteToggleRequest(BaseModel):
    """Request para alternar favorito."""

    is_favorite: bool