# app/schemas/learning/notebook.py
"""Schemas de request/response de cadernos."""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    folder: NotebookFolderResponse | None = None
    is_favorite: bool
    created_at: datetime
    updated_at: datetime
    
    # 🔥 CORREÇÃO BUG 1: Campo normal, em vez de @computed_field
    question_count: int = 0


class NotebookQuestionResponse(BaseModel):
    """Representa a relação entre o caderno e a questão."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    notebook_id: uuid.UUID
    question_id: uuid.UUID
    added_at: datetime
    question: Optional[QuestionListItem] = None

    @model_validator(mode='before')
    @classmethod
    def safe_load_question(cls, data: Any) -> Any:
        """
        🔥 CORREÇÃO DO ERRO 500 (MissingGreenlet): Impede que o Pydantic
        tente acessar um relacionamento ('question') não previamente carregado
        numa query individual de POST, o que gerava um crash interno no FastAPI.
        """
        if hasattr(data, '_sa_instance_state'):
            state = data._sa_instance_state
            has_question = 'question' in state.dict
            return {
                "id": data.id,
                "notebook_id": data.notebook_id,
                "question_id": data.question_id,
                "added_at": data.added_at,
                "question": state.dict['question'] if has_question else None
            }
        return data


class NotebookDetailResponse(NotebookResponse):
    """Resposta detalhada de um caderno (com questões)."""

    # 🔥 CORREÇÃO BUG 3: Alinhado à expectativa do Frontend (ApiNotebookQuestion[])
    questions: list[NotebookQuestionResponse] = Field(default_factory=list)


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