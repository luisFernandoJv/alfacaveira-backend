"""Plano de assinatura (Mensal, Semestral, Anual)."""

import uuid

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import BillingPeriod


class Plan(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(110), unique=True, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    billing_period: Mapped[BillingPeriod] = mapped_column(
        PGEnum(
            BillingPeriod,
            name="billing_period",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    # Cache derivado de `PlanFeature` (fonte de verdade normalizada),
    # reconstruído por `PlanService._rebuild_features_cache` sempre que a
    # associação plano/feature muda. Nunca escrito diretamente fora dali.
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Relacionamentos ------------------------------------------------- #
    # Relação com features do plano
    plan_features: Mapped[list["PlanFeature"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
    )

    # Relação com subscriptions: usa `plan_id` como FK (não `pending_plan_id`)
    # O `foreign_keys` é obrigatório porque agora há duas FKs entre plans e subscriptions
    # (plan_id e pending_plan_id), e o SQLAlchemy não consegue decidir sozinho qual usar.
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="plan",
        foreign_keys="Subscription.plan_id",  # <-- ESSENCIAL: desambigua a FK
    )