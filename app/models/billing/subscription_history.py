"""SubscriptionHistory: trilha de auditoria (append-only) de toda transição
de status ou de plano de uma assinatura.

Nunca é atualizada nem apagada — apenas inserida por `SubscriptionService`
dentro da mesma transação que muda a `Subscription`. `from_plan_id` fica
`None` na criação (não havia plano anterior).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import UUIDPKMixin
from app.models.enums import SubscriptionHistoryReason, SubscriptionStatus


class SubscriptionHistory(UUIDPKMixin, Base):
    __tablename__ = "subscription_history"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL")
    )
    to_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[SubscriptionStatus | None] = mapped_column(
        PGEnum(
            SubscriptionStatus,
            name="subscription_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        )
    )
    to_status: Mapped[SubscriptionStatus] = mapped_column(
        PGEnum(
            SubscriptionStatus,
            name="subscription_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    reason: Mapped[SubscriptionHistoryReason] = mapped_column(
        PGEnum(
            SubscriptionHistoryReason,
            name="subscription_history_reason",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    # Sem TimestampMixin: este registro é imutável, só precisa do momento da
    # transição (não faz sentido ter `updated_at` em um evento de auditoria).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    subscription: Mapped["Subscription"] = relationship(back_populates="history")