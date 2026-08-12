"""Modelo de ranking de usuários."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class UserRanking(UUIDPKMixin, TimestampMixin, Base):
    """
    Posição do usuário no ranking.

    Pontuação calculada com base em:
    - Questões respondidas (10 pontos cada)
    - Acertos (5 pontos adicionais)
    - Sequência de estudos (2 pontos por dia)
    - Bônus por consistência
    """

    __tablename__ = "user_rankings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_ranking"),
        Index("ix_user_rankings_rank", "rank"),
        Index("ix_user_rankings_total_points", "total_points"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Métricas principais
    total_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    questions_answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_answers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Rankings por período
    weekly_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monthly_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Posições (calculadas pelo worker)
    rank: Mapped[int | None] = mapped_column(Integer, index=True)
    rank_weekly: Mapped[int | None] = mapped_column(Integer)
    rank_monthly: Mapped[int | None] = mapped_column(Integer)

    # Timestamps
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relacionamentos
    user: Mapped["User"] = relationship()