"""Tags livres de questões (M2M)."""

import uuid

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin

question_tag_links = Table(
    "question_tag_links",
    Base.metadata,
    Column("question_id", UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("question_tags.id", ondelete="CASCADE"), primary_key=True),
)


class QuestionTag(UUIDPKMixin, TimestampMixin, Base):
    """Tag reutilizável entre questões (ex.: 'pegadinha', 'jurisprudência 2024')."""

    __tablename__ = "question_tags"

    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(90), unique=True, nullable=False, index=True)

    questions: Mapped[list["Question"]] = relationship(
        secondary=question_tag_links, back_populates="tags"
    )
