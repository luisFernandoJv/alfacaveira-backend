"""Schemas de request/response de moldes de simulado (`ExamTemplate`)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import QuestionDifficulty


class ExamTemplateCreateRequest(BaseModel):
    """Filtros + parâmetros usados para montar o molde de um simulado.

    Espelha os filtros de `TrainingSessionCreateRequest` (practice), exceto
    pelo nome do campo de quantidade (`question_count`, para bater com a
    coluna do modelo) e pelos campos exclusivos de simulado
    (`time_limit_minutes`, `is_public`).
    """

    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    discipline_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    exam_board_id: uuid.UUID | None = None
    exam_edition_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    difficulty: QuestionDifficulty | None = None
    tag_id: uuid.UUID | None = None
    question_count: int = Field(default=10, ge=1, le=100)
    time_limit_minutes: int | None = Field(default=None, ge=1)
    is_public: bool = False
    # ETAPA (2026-08-15): suporta "Banco de Questões → Selecionar → Criar
    # Simulado" (Fase 6 do roadmap). Quando informado, o molde usa
    # exatamente essas questões (na ordem enviada) em vez de sortear por
    # filtro — os demais filtros acima são ignorados nesse caso.
    # `question_count`, se enviado, também é ignorado: o service usa
    # `len(question_ids)`. Limite de 100 é o mesmo de `question_count`
    # (`ge=1, le=100`), validado no service (lista, não permite bound direto
    # no `Field` do jeito limpo que o `le` faz para `int`).
    question_ids: list[uuid.UUID] | None = None


class ExamTemplateListItem(BaseModel):
    """Item de listagem de moldes visíveis ao usuário (públicos + próprios)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    question_count: int
    time_limit_minutes: int | None
    is_public: bool
    created_by: uuid.UUID | None
    created_at: datetime


class ExamTemplateDetailResponse(BaseModel):
    """Detalhe de um molde de simulado."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    question_count: int
    time_limit_minutes: int | None
    is_public: bool
    created_by: uuid.UUID | None
    created_at: datetime