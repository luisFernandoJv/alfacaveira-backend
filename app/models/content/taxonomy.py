"""Dimensões normalizadas de classificação de questões.

Disciplina -> Assunto -> Subassunto (hierarquia de 3 níveis).
"""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class Discipline(UUIDPKMixin, TimestampMixin, Base):
    """Disciplina (ex.: Direito Penal, Português, Raciocínio Lógico)."""

    __tablename__ = "disciplines"

    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)

    subjects: Mapped[list["Subject"]] = relationship(back_populates="discipline")
    # `viewonly` implícito não é usado aqui de propósito: Flashcard.discipline_id
    # é SET NULL on delete, então apagar uma Discipline com flashcards vinculados
    # é uma operação válida (só desvincula), não algo que deva ser bloqueado
    # nem versionado por esta relationship.
    flashcards: Mapped[list["Flashcard"]] = relationship(back_populates="discipline")


class Subject(UUIDPKMixin, TimestampMixin, Base):
    """Assunto dentro de uma disciplina (ex.: Crimes contra a pessoa)."""

    __tablename__ = "subjects"

    discipline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disciplines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(210), nullable=False, index=True)

    discipline: Mapped["Discipline"] = relationship(back_populates="subjects")
    topics: Mapped[list["Topic"]] = relationship(back_populates="subject")


class Topic(UUIDPKMixin, TimestampMixin, Base):
    """Subassunto dentro de um assunto (ex.: Homicídio qualificado)."""

    __tablename__ = "topics"

    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(210), nullable=False, index=True)

    subject: Mapped["Subject"] = relationship(back_populates="topics")