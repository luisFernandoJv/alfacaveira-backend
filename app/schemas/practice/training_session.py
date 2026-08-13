"""Schemas de request/response de sessões de treino."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import QuestionDifficulty
from app.schemas.content.exam_source import (
    ExamBoardResponse,
    ExamEditionResponse,
    OrganizationResponse,
)
from app.schemas.content.question import QuestionAlternativePublicResponse, QuestionTagResponse
from app.schemas.content.taxonomy import DisciplineResponse, SubjectResponse, TopicResponse


class TrainingSessionCreateRequest(BaseModel):
    """Filtros usados para montar a sessão + quantidade de questões desejada.

    Espelha `QuestionFilters` (content), exceto `status`/`search`, que não
    fazem sentido para montar um treino (treino só usa questões publicadas).
    """

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
    
    # 🔥 NOVO: Lista explícita de IDs de questões para criar a sessão
    # Se fornecido, ignora todos os outros filtros
    question_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=100,
        description="Lista explícita de IDs de questões para montar a sessão"
    )
    notebook_id: uuid.UUID | None = Field(
        default=None,
        description="ID do caderno para criar sessão a partir das questões do caderno"
    )


class TrainingSessionQuestionResponse(BaseModel):
    """Questão dentro de uma sessão, na ordem de apresentação — sem gabarito.

    Inclui os metadados de prova (banca, edição, órgão, ano, tags) para que a
    tela de resolução não precise de uma segunda chamada para exibi-los.
    """

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
    position: int
    answered: bool


class TrainingSessionListItem(BaseModel):
    """Item de listagem do histórico de sessões do usuário."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    total_questions: int
    correct_count: int
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class TrainingSessionDetailResponse(BaseModel):
    """Detalhe de uma sessão: metadados + questões na ordem, sem gabarito."""

    id: uuid.UUID
    total_questions: int
    correct_count: int
    started_at: datetime
    finished_at: datetime | None
    current_question_index: int
    questions: list[TrainingSessionQuestionResponse]


class TrainingSessionPositionUpdateRequest(BaseModel):
    """Nova posição (índice da questão) que o aluno está vendo na sessão."""

    current_question_index: int = Field(ge=0)


class TrainingSessionPositionResponse(BaseModel):
    """Confirmação da posição salva — resposta enxuta, sem recarregar as
    questões inteiras da sessão a cada troca de posição."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    current_question_index: int