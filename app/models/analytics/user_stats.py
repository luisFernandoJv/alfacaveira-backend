"""Estatísticas pessoais pré-agregadas do aluno.

Estas tabelas são escritas por workers em background (a partir dos dados
crus de `question_attempts`), não calculadas on-the-fly a cada request —
é o que permite o Dashboard responder em milissegundos mesmo com milhões
de tentativas de resposta na tabela de origem.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.base import UUIDPKMixin


class UserDailyStat(UUIDPKMixin, Base):
    """Resumo diário de atividade (alimenta o gráfico de evolução semanal)."""

    __tablename__ = "user_daily_stats"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    questions_answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    time_studied_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_user_daily_stat"),)


class UserSubjectStat(UUIDPKMixin, Base):
    """Resumo por disciplina (alimenta 'Disciplinas mais estudadas')."""

    __tablename__ = "user_subject_stats"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    discipline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disciplines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    questions_answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "discipline_id", name="uq_user_subject_stat"),)


class StudyStreak(Base):
    """Sequência de dias estudados consecutivos. Chave primária = user_id."""

    __tablename__ = "study_streaks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_study_date: Mapped[date | None] = mapped_column(Date)
