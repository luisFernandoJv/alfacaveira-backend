"""Schemas de request/response de estado do usuário em uma questão."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FavoriteToggleRequest(BaseModel):
    """Alterna o favorito da questão para o valor informado."""

    is_favorite: bool


class NoteUpsertRequest(BaseModel):
    """Cria ou substitui a anotação pessoal do usuário para a questão.

    Enviar `note` como string vazia equivale a deletar a anotação —
    o service persiste NULL neste caso.
    """

    note: str = Field(max_length=5000)


class UserQuestionStateResponse(BaseModel):
    """Estado atual do usuário para uma questão (favorito + anotação)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    is_favorite: bool
    personal_note: str | None
    noted_at: datetime | None
    updated_at: datetime