"""Modelo de revisão espaçada de questões."""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ReviewStatus(str, enum.Enum):
    PENDENTE = "pendente"
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDA = "concluida"
    PULAR = "pular"


class ReviewPriority(str, enum.Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


class Review(UUIDPKMixin, TimestampMixin, Base):
    """Revisão espaçada de uma questão para um usuário."""

    __tablename__ = "reviews"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[ReviewStatus] = mapped_column(
        PGEnum(
            ReviewStatus,
            name="review_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ReviewStatus.PENDENTE,
        index=True,
    )
    priority: Mapped[ReviewPriority] = mapped_column(
        PGEnum(
            ReviewPriority,
            name="review_priority",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ReviewPriority.MEDIA,
        index=True,
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # --- Relacionamentos ---
    question: Mapped["Question"] = relationship(
        foreign_keys=[question_id],
        viewonly=True,
    )