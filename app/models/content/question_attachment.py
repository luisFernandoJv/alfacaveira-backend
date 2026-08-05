"""Anexos de uma questão (imagens do enunciado, PDFs de apoio, etc.)."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import AttachmentType


class QuestionAttachment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "question_attachments"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[AttachmentType] = mapped_column(
        PGEnum(
            AttachmentType,
            name="attachment_type",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ), nullable=False
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(500))

    question: Mapped["Question"] = relationship(back_populates="attachments")
