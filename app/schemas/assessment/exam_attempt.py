"""Schemas de request/response de execuções de simulado (`ExamAttempt`).

Submissão de resposta reutiliza `AnswerSubmitRequest`/`AnswerResultResponse`
de `app.schemas.practice.question_attempt` — mesmo contrato de treino, já
que ambos escrevem na mesma tabela `QuestionAttempt` (Etapa 8).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ExamAttemptStatus, QuestionDifficulty
from app.schemas.content.question import QuestionAlternativePublicResponse
from app.schemas.content.taxonomy import DisciplineResponse, SubjectResponse, TopicResponse


class ExamAttemptStartRequest(BaseModel):
    """Molde a partir do qual o simulado será montado."""

    exam_template_id: uuid.UUID


class ExamAttemptQuestionResponse(BaseModel):
    """Questão dentro de um simulado, na ordem de apresentação — sem gabarito."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement: str
    discipline: DisciplineResponse
    subject: SubjectResponse | None
    topic: TopicResponse | None
    difficulty: QuestionDifficulty
    alternatives: list[QuestionAlternativePublicResponse]
    position: int
    answered: bool


class ExamAttemptListItem(BaseModel):
    """Item de listagem do histórico de simulados do usuário."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exam_template_id: uuid.UUID
    status: ExamAttemptStatus
    total_questions: int
    correct_count: int
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class ExamAttemptDetailResponse(BaseModel):
    """Detalhe de um simulado: metadados + questões na ordem, sem gabarito."""

    id: uuid.UUID
    exam_template_id: uuid.UUID
    status: ExamAttemptStatus
    time_limit_minutes: int | None
    total_questions: int
    correct_count: int
    started_at: datetime
    finished_at: datetime | None
    questions: list[ExamAttemptQuestionResponse]