# app/models/content/notebook.py
"""Modelo de caderno (notebook) do usuário."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


# ============================================================================
# TABELA DE RELACIONAMENTO N:N (Notebook <-> NotebookTag)
# ============================================================================

notebook_tag_links = Table(
    "notebook_tag_links",
    Base.metadata,
    Column("notebook_id", UUID(as_uuid=True), ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("notebook_tags.id", ondelete="CASCADE"), primary_key=True),
)


# ============================================================================
# MODELOS
# ============================================================================

class NotebookFolder(UUIDPKMixin, TimestampMixin, Base):
    """Pasta para organizar cadernos."""

    __tablename__ = "notebook_folders"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notebook_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Relacionamentos
    user: Mapped["User"] = relationship()
    parent: Mapped["NotebookFolder"] = relationship(remote_side="NotebookFolder.id")
    children: Mapped[list["NotebookFolder"]] = relationship(
        cascade="all, delete-orphan",
    )
    notebooks: Mapped[list["Notebook"]] = relationship(back_populates="folder")


class NotebookTag(UUIDPKMixin, TimestampMixin, Base):
    """Tag para organizar cadernos."""

    __tablename__ = "notebook_tags"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(90), nullable=False, index=True)

    # Relacionamentos
    user: Mapped["User"] = relationship()
    notebooks: Mapped[list["Notebook"]] = relationship(
        secondary=notebook_tag_links,
        back_populates="tags",
    )


class Notebook(UUIDPKMixin, TimestampMixin, Base):
    """Caderno de estudo do usuário."""

    __tablename__ = "notebooks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_favorite: Mapped[bool] = mapped_column(default=False, nullable=False)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notebook_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Campo auxiliar para contagem de questões (não persistido)
    question_count: int = 0

    # Relacionamentos
    user: Mapped["User"] = relationship()
    folder: Mapped["NotebookFolder"] = relationship(back_populates="notebooks")
    questions: Mapped[list["NotebookQuestion"]] = relationship(
        back_populates="notebook",
        cascade="all, delete-orphan",
        order_by="NotebookQuestion.added_at.desc()",
    )
    tags: Mapped[list["NotebookTag"]] = relationship(
        secondary=notebook_tag_links,
        back_populates="notebooks",
    )


class NotebookQuestion(UUIDPKMixin, Base):
    """Questão dentro de um caderno."""

    __tablename__ = "notebook_questions"
    __table_args__ = (
        UniqueConstraint("notebook_id", "question_id", name="uq_notebook_question"),
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
    note: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    # Relacionamentos
    notebook: Mapped["Notebook"] = relationship(back_populates="questions")
    question: Mapped["Question"] = relationship()