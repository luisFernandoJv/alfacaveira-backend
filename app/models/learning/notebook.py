# app/models/learning/notebook.py
"""Modelo de caderno do usuário."""

import uuid
from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin

# 🔥 CORREÇÃO: Importar a tabela do arquivo correto
from app.models.learning.notebook_tag import notebook_tag_links
from app.models.learning.notebook_folder import NotebookFolder
from app.models.learning.notebook_question import NotebookQuestion
from app.models.learning.notebook_tag import NotebookTag


class Notebook(UUIDPKMixin, TimestampMixin, Base):
    """Caderno do usuário para organizar questões."""

    __tablename__ = "notebooks"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_notebook_user_name"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notebook_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # Relacionamentos
    folder: Mapped[Optional["NotebookFolder"]] = relationship(
        "NotebookFolder",
        back_populates="notebooks",
        foreign_keys=[folder_id],
    )
    questions: Mapped[List["NotebookQuestion"]] = relationship(
        "NotebookQuestion",
        back_populates="notebook",
        cascade="all, delete-orphan",
        order_by="NotebookQuestion.added_at.desc()",
    )
    tags: Mapped[List["NotebookTag"]] = relationship(
        "NotebookTag",
        secondary=notebook_tag_links,
        back_populates="notebooks",
    )