"""Histórico unificado de respostas do aluno.

Decisão de modelagem: em vez de duplicar a lógica de "resposta" dentro de
treino e de simulado separadamente, toda resposta (venha de onde vier) gera
uma linha aqui. `session_type` + `session_id` apontam para a origem (frouxo,
sem FK física, pois pode referenciar `training_sessions` ou `exam_attempts`).
Isso simplifica MUITO o módulo de Estatísticas e a tela de Histórico: uma
única tabela para consultar "tudo que o aluno já respondeu".
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import UUIDPKMixin
from app.models.enums import SessionType


class QuestionAttempt(UUIDPKMixin, Base):
    __tablename__ = "question_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    session_type: Mapped[SessionType] = mapped_column(
        PGEnum(
            SessionType,
            name="session_type",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    selected_alternative_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_alternatives.id")
    )
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    question: Mapped["Question"] = relationship()
