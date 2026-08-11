"""Assinatura ativa de um usuário a um plano."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import SubscriptionStatus


class Subscription(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        PGEnum(
            SubscriptionStatus,
            name="subscription_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        # PENDENTE, não ATIVA (ADR-003 / ADR-014, PROMPT 05): este default
        # do lado do SQLAlchemy só se aplica se `status` não for passado
        # explicitamente ao construtor — `SubscriptionService.create_subscription`
        # sempre define o status na criação, então isto é sobretudo
        # documentação de que "assinatura sem confirmação" é o estado
        # seguro por padrão, nunca ATIVA.
        default=SubscriptionStatus.PENDENTE,
        index=True,
    )
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Dunning (PROMPT 11, roadmap item 11) ---------------------------- #
    # Só têm significado enquanto `status == INADIMPLENTE`; zerados/limpos
    # ao sair desse estado (recuperada -> ATIVA, ou expirada -> EXPIRADA).
    # `dunning_attempts` conta tentativas de recobrança já feitas desde a
    # transição ATIVA -> INADIMPLENTE mais recente (não é cumulativo entre
    # ciclos de inadimplência distintos).
    dunning_attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    # Próxima tentativa de recobrança elegível (NULL quando não há retry
    # agendado — ex.: fora de INADIMPLENTE, ou tentativas já esgotadas).
    dunning_next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # Prazo final do grace period — quando `now >= dunning_grace_period_ends_at`
    # e a assinatura ainda está INADIMPLENTE, o job de dunning expira (EXPIRADA)
    # independentemente de quantas tentativas de retry ainda restariam.
    dunning_grace_period_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # --- Upgrade/Downgrade (PROMPT 12, roadmap item 12) ------------------ #
    # `pending_plan_id` guarda o plano para o qual a assinatura será
    # trocada no próximo ciclo de cobrança (usado para downgrade).
    # NULL quando não há downgrade agendado.
    pending_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Data em que o downgrade entra em vigor (normalmente `current_period_end`).
    # NULL quando não há downgrade agendado.
    pending_plan_effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # --- Relacionamentos ------------------------------------------------- #
    plan: Mapped["Plan"] = relationship(foreign_keys=[plan_id], back_populates="subscriptions")
    pending_plan: Mapped["Plan | None"] = relationship(foreign_keys=[pending_plan_id])
    payments: Mapped[list["Payment"]] = relationship(back_populates="subscription")
    history: Mapped[list["SubscriptionHistory"]] = relationship(
        back_populates="subscription", order_by="SubscriptionHistory.created_at.desc()"
    )

    # Timestamp do último lembrete enviado para este período.
    # NULL = nunca enviado; usado para não enviar mais de uma vez por período.
    renewal_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )