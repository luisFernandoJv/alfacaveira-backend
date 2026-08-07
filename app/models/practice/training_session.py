"""Sessão de treino (Novo Treino / resolução avulsa de questões)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class TrainingSession(UUIDPKMixin, TimestampMixin, Base):
    """Sessão de estudo criada a partir de um conjunto de filtros."""

    __tablename__ = "training_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Snapshot dos filtros usados para montar a sessão (disciplina, banca, ano, ...).
    filters_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Índice (0-based) da última questão vista pelo aluno nesta sessão —
    # permite restaurar `/questoes/resolver?session={id}` na mesma posição
    # após reload, sem depender de "primeira não respondida" (o aluno pode
    # ter avançado sem responder, ex.: pular questão).
    current_question_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    questions: Mapped[list["TrainingSessionQuestion"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="TrainingSessionQuestion.position"
    )


class TrainingSessionQuestion(UUIDPKMixin, Base):
    """Questão dentro de uma sessão de treino, na ordem em que foi apresentada."""

    __tablename__ = "training_session_questions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    session: Mapped["TrainingSession"] = relationship(back_populates="questions")