"""Estado de revisão espaçada do flashcard (algoritmo SM-2).

Campos padrão do SM-2: easiness_factor (>=1.3), interval_days, repetitions e
due_date. `last_grade` guarda a última nota dada pelo aluno (0-3, mapeada em
FlashcardGrade) para fins de estatística/depuração do algoritmo.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import FlashcardGrade


class FlashcardReview(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "flashcard_reviews"

    flashcard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flashcards.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    easiness_factor: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_grade: Mapped[FlashcardGrade | None] = mapped_column(
        PGEnum(
            FlashcardGrade,
            name="flashcard_grade",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        )
    )

    flashcard: Mapped["Flashcard"] = relationship(back_populates="review_state")
