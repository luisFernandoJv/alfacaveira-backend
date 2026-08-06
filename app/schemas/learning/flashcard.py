"""Schemas de request/response de flashcards e revisão espaçada (SM-2)."""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FlashcardGrade
from app.schemas.content.taxonomy import DisciplineResponse

if TYPE_CHECKING:
    from app.models.learning.flashcard import Flashcard


class FlashcardCreateRequest(BaseModel):
    """Criação manual de um flashcard pelo aluno."""

    front: str = Field(min_length=1)
    back: str = Field(min_length=1)
    discipline_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None


class FlashcardCreateFromQuestionRequest(BaseModel):
    """Criação automática a partir de uma questão já respondida.

    `front`/`back` são opcionais: quando omitidos, o service monta o cartão a
    partir do enunciado e do gabarito comentado da questão de origem.
    """

    question_id: uuid.UUID
    front: str | None = None
    back: str | None = None


class FlashcardUpdateRequest(BaseModel):
    """PATCH parcial: só os campos enviados são alterados (`exclude_unset`)."""

    front: str | None = Field(default=None, min_length=1)
    back: str | None = Field(default=None, min_length=1)
    discipline_id: uuid.UUID | None = None


class FlashcardReviewRequest(BaseModel):
    """Avaliação de confiança enviada pelo aluno ao revisar um flashcard."""

    grade: FlashcardGrade


class FlashcardReviewStateResponse(BaseModel):
    """Estado atual de revisão espaçada (SM-2) de um flashcard."""

    model_config = ConfigDict(from_attributes=True)

    easiness_factor: float
    interval_days: int
    repetitions: int
    due_date: date
    last_reviewed_at: datetime | None
    last_grade: FlashcardGrade | None


class FlashcardResponse(BaseModel):
    """Item de listagem/detalhe de um flashcard, com seu estado de revisão."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    question_id: uuid.UUID | None
    discipline_id: uuid.UUID | None
    discipline: DisciplineResponse | None
    front: str
    back: str
    review: FlashcardReviewStateResponse
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, flashcard: "Flashcard") -> "FlashcardResponse":
        """Constrói a resposta a partir do model ORM.

        Necessário porque o atributo da relação no model é `review_state`
        (nome descritivo no domínio) mas o contrato de API expõe `review`
        (mais direto para o client) — `model_validate` sozinho não faria
        esse remapeamento de nome.
        """
        return cls(
            id=flashcard.id,
            user_id=flashcard.user_id,
            question_id=flashcard.question_id,
            discipline_id=flashcard.discipline_id,
            discipline=(
                DisciplineResponse.model_validate(flashcard.discipline)
                if flashcard.discipline
                else None
            ),
            front=flashcard.front,
            back=flashcard.back,
            review=FlashcardReviewStateResponse.model_validate(flashcard.review_state),
            created_at=flashcard.created_at,
            updated_at=flashcard.updated_at,
        )


class FlashcardReviewResultResponse(BaseModel):
    """Retorno de `POST /flashcards/{id}/review`: cartão + próxima revisão."""

    flashcard: FlashcardResponse
    is_due_again_today: bool


class FlashcardListResponse(BaseModel):
    """Página de flashcards, com metadados de agendamento."""

    items: list[FlashcardResponse]
    next_cursor: str | None = None
    has_more: bool = False


class FlashcardStatsResponse(BaseModel):
    """Estatísticas agregadas do módulo, usadas no cabeçalho da tela."""

    total: int
    due_today: int
    reviewed_today: int
    reviewed_total: int
    retention_rate: float
    streak_days: int
    by_discipline: list["FlashcardDisciplineStats"]


class FlashcardDisciplineStats(BaseModel):
    discipline_id: uuid.UUID | None
    discipline_name: str
    total: int
    due_today: int


FlashcardStatsResponse.model_rebuild()
