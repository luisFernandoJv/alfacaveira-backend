"""Schemas de request/response de questões."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import QuestionAnswerStatus, QuestionDifficulty, QuestionStatus
from app.schemas.content.exam_source import (
    ExamBoardResponse,
    ExamEditionResponse,
    OrganizationResponse,
)
from app.schemas.content.taxonomy import DisciplineResponse, SubjectResponse, TopicResponse

_VALID_LETTERS = "ABCDE"


class QuestionTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class QuestionAlternativeInput(BaseModel):
    """Alternativa enviada na criação/edição de uma questão."""

    letter: str = Field(min_length=1, max_length=1)
    text: str = Field(min_length=1)
    is_correct: bool = False

    @field_validator("letter")
    @classmethod
    def _letter_must_be_valid(cls, value: str) -> str:
        letter = value.upper()
        if letter not in _VALID_LETTERS:
            raise ValueError(f"Letra de alternativa inválida: '{value}'. Use A-E.")
        return letter


class QuestionAlternativeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    letter: str
    text: str
    is_correct: bool


class QuestionAlternativePublicResponse(BaseModel):
    """Alternativa exposta durante a resolução (treino/simulado) — sem gabarito.

    Igual a `QuestionAlternativeResponse`, mas sem `is_correct`: usada nos
    endpoints em que a questão ainda não foi respondida pelo usuário, para
    não vazar a resposta correta pela API antes da hora.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    letter: str
    text: str


class QuestionCreateRequest(BaseModel):
    discipline_id: uuid.UUID
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    exam_board_id: uuid.UUID
    exam_edition_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)

    difficulty: QuestionDifficulty
    statement: str = Field(min_length=1)
    explanation: str | None = None

    alternatives: list[QuestionAlternativeInput] = Field(min_length=2, max_length=5)
    tag_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_alternatives(self) -> "QuestionCreateRequest":
        letters = [alt.letter for alt in self.alternatives]
        if len(letters) != len(set(letters)):
            raise ValueError("Letras de alternativas duplicadas.")
        correct = [alt for alt in self.alternatives if alt.is_correct]
        if len(correct) != 1:
            raise ValueError("Exatamente uma alternativa deve ser marcada como correta.")
        return self


class QuestionUpdateRequest(BaseModel):
    """PATCH parcial: só os campos enviados são alterados (`exclude_unset`)."""

    discipline_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    exam_board_id: uuid.UUID | None = None
    exam_edition_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)

    difficulty: QuestionDifficulty | None = None
    statement: str | None = Field(default=None, min_length=1)
    explanation: str | None = None

    # Se enviado, substitui integralmente o conjunto de alternativas.
    alternatives: list[QuestionAlternativeInput] | None = Field(
        default=None, min_length=2, max_length=5
    )
    tag_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def _validate_alternatives(self) -> "QuestionUpdateRequest":
        if self.alternatives is None:
            return self
        letters = [alt.letter for alt in self.alternatives]
        if len(letters) != len(set(letters)):
            raise ValueError("Letras de alternativas duplicadas.")
        correct = [alt for alt in self.alternatives if alt.is_correct]
        if len(correct) != 1:
            raise ValueError("Exatamente uma alternativa deve ser marcada como correta.")
        return self


class QuestionStatusUpdateRequest(BaseModel):
    status: QuestionStatus


class QuestionListItem(BaseModel):
    """Item de listagem (público, filtrável) — sem gabarito/explicação."""

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
    status: QuestionStatus
    tags: list[QuestionTagResponse]
    created_at: datetime

    # ETAPA 3 (sessão 6): estado do usuário autenticado para esta questão.
    # Não são colunas de `Question` — `QuestionService.list_questions`
    # calcula em lote (a partir de `UserQuestionState`/`QuestionAttempt`) e
    # atribui como atributo transiente no objeto ORM antes de serializar.
    # Default aqui é só uma rede de segurança para o caso (não esperado) de
    # o atributo não ter sido setado; a fonte de verdade é sempre o cálculo
    # do service.
    is_favorite: bool = False
    answer_status: QuestionAnswerStatus = QuestionAnswerStatus.NAO_RESPONDIDA


class QuestionDetailResponse(BaseModel):
    """Detalhe completo de uma questão, incluindo alternativas e gabarito."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement: str
    explanation: str | None
    correct_alternative_letter: str
    discipline: DisciplineResponse
    subject: SubjectResponse | None
    topic: TopicResponse | None
    exam_board: ExamBoardResponse
    exam_edition: ExamEditionResponse | None
    organization: OrganizationResponse | None
    year: int | None
    difficulty: QuestionDifficulty
    status: QuestionStatus
    alternatives: list[QuestionAlternativeResponse]
    tags: list[QuestionTagResponse]
    created_at: datetime
    updated_at: datetime