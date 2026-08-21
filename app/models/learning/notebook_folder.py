# app/models/learning/notebook_folder.py
"""Modelo de pasta para organização hierárquica de cadernos."""

import uuid
from typing import List, Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class NotebookFolder(UUIDPKMixin, TimestampMixin, Base):
    """Pasta para organizar cadernos em hierarquia."""

    __tablename__ = "notebook_folders"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_notebook_folder_user_name"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notebook_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Relacionamentos
    parent: Mapped[Optional["NotebookFolder"]] = relationship(
        "NotebookFolder",
        remote_side="NotebookFolder.id",
        backref="children",
        single_parent=True,
    )
    notebooks: Mapped[List["Notebook"]] = relationship(
        "Notebook",
        back_populates="folder",
        cascade="save-update, merge",
    )