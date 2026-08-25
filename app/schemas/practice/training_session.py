# app/schemas/practice/training_session.py
"""Schemas de request/response de sessões de treino."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import MAX_BULK_QUESTION_SELECTION
from app.models.enums import QuestionDifficulty
from app.schemas.content.exam_source import (
    ExamBoardResponse,
    ExamEditionResponse,
    OrganizationResponse,
)
from app.schemas.content.question import (
    QuestionAlternativePublicResponse,
    QuestionAttachmentResponse,
    QuestionTagResponse,
)
from app.schemas.content.taxonomy import DisciplineResponse, SubjectResponse, TopicResponse


class TrainingSessionCreateRequest(BaseModel):
    """Filtros usados para montar a sessão + quantidade de questões desejada."""

    discipline_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    exam_board_id: uuid.UUID | None = None
    exam_edition_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    difficulty: QuestionDifficulty | None = None
    tag_id: uuid.UUID | None = None
    quantity: int = Field(default=10, ge=1, le=100)
    
    question_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=MAX_BULK_QUESTION_SELECTION,
        description="Lista explícita de IDs de questões para montar a sessão"
    )
    # 🔥 CORREÇÃO: Adicionar notebook_id
    notebook_id: uuid.UUID | None = Field(
        default=None,
        description="ID do caderno para criar sessão a partir das questões do caderno"
    )


class TrainingSessionQuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    statement: str
    discipline: DisciplineResponse
    subject: SubjectResponse | None
    topic: TopicResponse | None
    exam_board: ExamBoardResponse
    exam_edition: ExamEditionResponse | None
    organization: OrganizationResponse | None
    year: int | None
    difficulty: QuestionDifficulty
    alternatives: list[QuestionAlternativePublicResponse]
    tags: list[QuestionTagResponse]
    # Imagens do enunciado — a mesma peça que aparece no Banco de Questões
    # (`QuestionDetailResponse.attachments`), exposta aqui também porque a
    # resolução real acontece na sessão de treino, não no detalhe avulso.
    attachments: list[QuestionAttachmentResponse] = Field(default_factory=list)
    position: int
    answered: bool
    # Preenchidos SOMENTE quando `answered=True` — a questão já foi
    # respondida em uma visita anterior a esta mesma sessão. É o que
    # permite o frontend reconstruir o resultado (`AnswerRecord`) ao
    # retomar a sessão, em vez de perder o "já respondi isso" toda vez
    # que a página é recarregada ou o aluno sai e volta.
    # Para questões ainda não respondidas, ficam `None` — o gabarito
    # nunca é exposto antes da resposta ser enviada.
    selected_alternative_id: uuid.UUID | None = None
    is_correct: bool | None = None
    correct_alternative_letter: str | None = None
    explanation: str | None = None


class TrainingSessionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    total_questions: int
    correct_count: int
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class TrainingSessionDetailResponse(BaseModel):
    id: uuid.UUID
    total_questions: int
    correct_count: int
    started_at: datetime
    finished_at: datetime | None
    current_question_index: int
    questions: list[TrainingSessionQuestionResponse]


class TrainingSessionPositionUpdateRequest(BaseModel):
    current_question_index: int = Field(ge=0)


class TrainingSessionPositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    current_question_index: int