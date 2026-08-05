"""Pagamento associado a uma assinatura (estrutura preparada, sem gateway ainda)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import PaymentStatus


class Payment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    status: Mapped[PaymentStatus] = mapped_column(
        PGEnum(
            PaymentStatus,
            name="payment_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=PaymentStatus.PENDENTE,
        index=True,
    )
    provider: Mapped[str | None] = mapped_column(String(50))
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    subscription: Mapped["Subscription"] = relationship(back_populates="payments")
