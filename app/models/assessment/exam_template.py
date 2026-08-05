"""Configuração/molde de um simulado (pode ser público ou pessoal)."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ExamTemplate(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "exam_templates"

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer)
    filters_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
