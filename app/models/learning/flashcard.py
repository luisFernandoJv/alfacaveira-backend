"""Flashcard do aluno, opcionalmente vinculado a uma questão de origem."""

import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class Flashcard(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "flashcards"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="SET NULL")
    )
    discipline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disciplines.id", ondelete="SET NULL")
    )
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)

    review_state: Mapped["FlashcardReview"] = relationship(back_populates="flashcard", uselist=False)
    # Somente leitura (sem back_populates): `Discipline` não precisa navegar até
    # os flashcards que a referenciam. Usada para exibir o "baralho" (agrupado
    # por disciplina) nas listagens sem N+1 (`selectinload` no repositório).
    discipline: Mapped["Discipline | None"] = relationship(viewonly=True)
