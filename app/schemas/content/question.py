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
    # Imagem opcional da própria alternativa (migration 0028). Sem isso, o
    # campo era descartado silenciosamente pelo Pydantic (extra ignorado
    # por padrão) — a UI mostrava sucesso ao salvar, mas nada era gravado.
    image_url: str | None = Field(default=None, max_length=1000)

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
    image_url: str | None = None


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
    image_url: str | None = None


class QuestionAttachmentInput(BaseModel):
    """Anexo enviado na criação/edição de questão.

    A imagem já deve estar no S3 (via `POST /questions/attachments/presign`)
    — aqui só se referencia a URL pública final do objeto.
    """

    type: str = Field(default="imagem")  # "imagem" | "arquivo"
    url: str = Field(min_length=1, max_length=1000)
    alt_text: str | None = Field(default=None, max_length=500)


class QuestionAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    url: str
    alt_text: str | None


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
    teacher_name: str | None = Field(default=None, max_length=120)

    alternatives: list[QuestionAlternativeInput] = Field(min_length=2, max_length=5)
    tag_ids: list[uuid.UUID] = Field(default_factory=list)
    # Imagens do enunciado/alternativas, já hospedadas no S3 (ver
    # QuestionAttachmentInput). Opcional — nem toda questão tem imagem.
    attachments: list[QuestionAttachmentInput] = Field(default_factory=list)

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
    teacher_name: str | None = Field(default=None, max_length=120)

    # Se enviado, substitui integralmente o conjunto de alternativas.
    alternatives: list[QuestionAlternativeInput] | None = Field(
        default=None, min_length=2, max_length=5
    )
    tag_ids: list[uuid.UUID] | None = None
    # Se enviado, substitui integralmente o conjunto de anexos (mesmo
    # comportamento já adotado para `alternatives`/`tag_ids`).
    attachments: list[QuestionAttachmentInput] | None = None

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
    # Anexos (imagens) da questão — expostos também na listagem para o
    # frontend poder mostrar um indicador/miniatura de "questão com imagem"
    # sem precisar abrir o detalhe.
    attachments: list[QuestionAttachmentResponse] = Field(default_factory=list)

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
    teacher_name: str | None
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
    attachments: list[QuestionAttachmentResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class FacetBucket(BaseModel):
    """Uma opção de uma dimensão de faceta + quantas questões ela teria,
    dentro dos filtros já aplicados (exceto o filtro da própria dimensão)."""

    id: str
    count: int


class QuestionFacetsResponse(BaseModel):
    """Resposta de `GET /questions/facets`.

    `total` é a contagem com TODOS os filtros aplicados (igual a
    `meta.total` de `GET /questions`). Cada lista de `FacetBucket` é
    calculada com todos os filtros aplicados MENOS o da própria dimensão —
    é o que permite ao frontend mostrar "Direito Penal (5.230)" ao lado de
    uma opção ainda não selecionada, refletindo o que aconteceria se o
    usuário a selecionasse.
    """

    total: int
    discipline_id: list[FacetBucket]
    subject_id: list[FacetBucket]
    topic_id: list[FacetBucket]
    exam_board_id: list[FacetBucket]
    organization_id: list[FacetBucket]
    year: list[FacetBucket]
    difficulty: list[FacetBucket]