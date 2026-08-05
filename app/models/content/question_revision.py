"""Histórico de alterações da questão — tabela de auditoria append-only.

Nunca é atualizada nem deletada: cada mudança relevante gera uma nova linha
com um snapshot (JSONB) do estado anterior, evitando que o histórico infle o
tamanho da linha principal de `questions`.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import UUIDPKMixin
from app.models.enums import QuestionRevisionType


class QuestionRevision(UUIDPKMixin, Base):
    __tablename__ = "question_revisions"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    change_type: Mapped[QuestionRevisionType] = mapped_column(
        PGEnum(
            QuestionRevisionType,
            name="question_revision_type",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ), nullable=False
    )
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    question: Mapped["Question"] = relationship(back_populates="revisions")
