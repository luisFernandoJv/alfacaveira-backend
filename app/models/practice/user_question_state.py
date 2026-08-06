"""Estado persistido do usuário em relação a uma questão específica.

Um registro por par (user_id, question_id) — criado na primeira interação
(favoritar ou salvar anotação) e atualizado nas subsequentes via upsert.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class UserQuestionState(UUIDPKMixin, TimestampMixin, Base):
    """Favorito + anotação pessoal do usuário para uma questão.

    Campos:
    - is_favorite: questão marcada como favorita.
    - personal_note: anotação livre; NULL quando nunca preenchida.
      A camada de serviço converte string vazia em NULL antes de persistir.
    - noted_at: timestamp da última vez em que a anotação foi salva.
    """

    __tablename__ = "user_question_states"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_favorite: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    personal_note: Mapped[str | None] = mapped_column(Text)
    noted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ------------------------------------------------------------------ #
    # Relacionamentos                                                       #
    # ------------------------------------------------------------------ #
    user: Mapped["User"] = relationship(back_populates="question_states")
    question: Mapped["Question"] = relationship(back_populates="user_states")

    # ------------------------------------------------------------------ #
    # Índices e constraints                                                 #
    # ------------------------------------------------------------------ #
    __table_args__ = (
        # Garante unicidade do par e serve de índice para lookups por
        # (user_id, question_id) — caso de uso mais comum (upsert + leitura
        # durante resolução de questão).
        UniqueConstraint("user_id", "question_id", name="uq_user_question_state"),
        # Índice parcial para a listagem de favoritas: filtrado em is_favorite=true,
        # mantendo o índice pequeno independentemente do volume de registros.
        Index(
            "ix_uqs_favorites",
            "user_id",
            postgresql_where="is_favorite = true",
        ),
        # Índice parcial para listar questões com anotação.
        Index(
            "ix_uqs_noted",
            "user_id",
            postgresql_where="personal_note IS NOT NULL",
        ),
    )