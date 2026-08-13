# app/models/learning/notebook_tag.py
"""Modelo de tags para cadernos."""

import uuid
from typing import List

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin

# 🔥 CORREÇÃO: Table com extend_existing para evitar duplicação
notebook_tag_links = Table(
    "notebook_tag_links",
    Base.metadata,
    Column(
        "notebook_id",
        UUID(as_uuid=True),
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        UUID(as_uuid=True),
        ForeignKey("notebook_tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    extend_existing=True,
)


class NotebookTag(UUIDPKMixin, TimestampMixin, Base):
    """Tag reutilizável para cadernos."""

    __tablename__ = "notebook_tags"

    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(90), unique=True, nullable=False, index=True)

    notebooks: Mapped[List["Notebook"]] = relationship(
        "Notebook",
        secondary=notebook_tag_links,
        back_populates="tags",
    )