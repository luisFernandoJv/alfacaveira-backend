"""Execução de um simulado por um aluno."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import ExamAttemptStatus


class ExamAttempt(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "exam_attempts"

    exam_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_templates.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ExamAttemptStatus] = mapped_column(
        PGEnum(
            ExamAttemptStatus,
            name="exam_attempt_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ExamAttemptStatus.EM_ANDAMENTO,
        index=True,
    )
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    questions: Mapped[list["ExamAttemptQuestion"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan", order_by="ExamAttemptQuestion.position"
    )


class ExamAttemptQuestion(UUIDPKMixin, Base):
    __tablename__ = "exam_attempt_questions"

    exam_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_alternative_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_alternatives.id")
    )
    is_correct: Mapped[bool | None] = mapped_column()
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)

    attempt: Mapped["ExamAttempt"] = relationship(back_populates="questions")
