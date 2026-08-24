"""Questão: entidade central do sistema, preparada para milhões de registros."""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import QuestionDifficulty, QuestionStatus


class Question(UUIDPKMixin, TimestampMixin, Base):
    """Questão de múltipla escolha.

    Totalmente normalizada: nenhuma string de classificação é repetida na
    própria linha, tudo referencia tabelas de dimensão por FK. `search_vector`
    é mantido por trigger no banco (Etapa 3 da migration) para full-text search
    sem depender de LIKE '%...%'.
    """

    __tablename__ = "questions"

    discipline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disciplines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="SET NULL"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    exam_board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_boards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    exam_edition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_editions.id", ondelete="SET NULL"), index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    year: Mapped[int | None] = mapped_column(Integer, index=True)

    difficulty: Mapped[QuestionDifficulty] = mapped_column(
        PGEnum(
            QuestionDifficulty,
            name="question_difficulty",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    status: Mapped[QuestionStatus] = mapped_column(
        PGEnum(
            QuestionStatus,
            name="question_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=QuestionStatus.RASCUNHO,
        index=True,
    )

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    correct_alternative_letter: Mapped[str] = mapped_column(String(1), nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    # Nome do professor autor do gabarito comentado (exibido no cartão de
    # comentário para o aluno). Livre — não é FK para `users`, pois nem todo
    # professor tem conta na plataforma; é só um rótulo editável pelo admin.
    teacher_name: Mapped[str | None] = mapped_column(String(120))

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Mantido via trigger de banco (to_tsvector) — não escrito pela aplicação.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    discipline: Mapped["Discipline"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    topic: Mapped["Topic | None"] = relationship()
    exam_board: Mapped["ExamBoard"] = relationship()
    exam_edition: Mapped["ExamEdition | None"] = relationship()
    organization: Mapped["Organization | None"] = relationship()

    alternatives: Mapped[list["QuestionAlternative"]] = relationship(
        back_populates="question", order_by="QuestionAlternative.letter", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["QuestionAttachment"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    revisions: Mapped[list["QuestionRevision"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    tags: Mapped[list["QuestionTag"]] = relationship(
        secondary="question_tag_links", back_populates="questions"
    )
    user_states: Mapped[list["UserQuestionState"]] = relationship(back_populates="question")

    __table_args__ = (
        # Índice composto para o conjunto de filtros usado pelo filters-panel do frontend.
        Index(
            "ix_questions_filter_composite",
            "discipline_id",
            "subject_id",
            "exam_board_id",
            "year",
            "difficulty",
            "status",
        ),
        Index("ix_questions_search_vector", "search_vector", postgresql_using="gin"),
    )


class QuestionAlternative(UUIDPKMixin, TimestampMixin, Base):
    """Alternativa (A-E) de uma questão."""

    __tablename__ = "question_alternatives"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    letter: Mapped[str] = mapped_column(String(1), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(default=False, nullable=False)

    question: Mapped["Question"] = relationship(back_populates="alternatives")

    __table_args__ = (UniqueConstraint("question_id", "letter", name="uq_question_alternative_letter"),)