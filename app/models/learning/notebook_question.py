# app/models/learning/notebook_question.py
"""Modelo de relação entre caderno e questão."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import UUIDPKMixin


class NotebookQuestion(UUIDPKMixin, Base):
    """Relação entre um caderno e uma questão."""

    __tablename__ = "notebook_questions"
    __table_args__ = (
        UniqueConstraint(
            "notebook_id",
            "question_id",
            name="uq_notebook_question_unique",
        ),
    )

    notebook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relacionamentos
    notebook: Mapped["Notebook"] = relationship(
        "Notebook",
        back_populates="questions",
    )
    question: Mapped["Question"] = relationship(
        "Question",
        viewonly=True,
    )