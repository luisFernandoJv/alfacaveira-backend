"""Schemas de request/response de tentativas de resposta (`QuestionAttempt`)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SessionType


class AnswerSubmitRequest(BaseModel):
    """Resposta enviada pelo aluno para uma questão da sessão.

    `selected_alternative_id=None` representa questão pulada (sem marcar
    nenhuma alternativa) — ainda assim gera um registro de tentativa, com
    `is_correct=False`, para não deixar buraco no histórico/estatísticas.
    """

    selected_alternative_id: uuid.UUID | None = None
    time_spent_seconds: int | None = Field(default=None, ge=0)


class AnswerResultResponse(BaseModel):
    """Resultado imediato de uma resposta: acerto/erro + gabarito comentado."""

    question_id: uuid.UUID
    selected_alternative_id: uuid.UUID | None
    correct_alternative_letter: str
    is_correct: bool
    explanation: str | None
    # Nome do professor autor do gabarito comentado — exibido no cartão de
    # comentário junto da explicação (ver `Question.teacher_name`).
    teacher_name: str | None = None


class QuestionAttemptListItem(BaseModel):
    """Item do histórico geral de respostas do usuário."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    session_type: SessionType
    session_id: uuid.UUID
    is_correct: bool | None
    time_spent_seconds: int | None
    answered_at: datetime