"""PlanFeature: associa um Plan a uma Feature, com limite opcional de quota.

`quota_limit`:
- Só é relevante quando `Feature.kind == FeatureKind.QUOTA`.
- `None` = ilimitado (ex.: STANDARD/PRO em "questões por dia").
- Um número = limite (ex.: FREE em "questões por dia" = 5).

Para Features booleanas, a simples existência de uma linha `PlanFeature`
(plan_id, feature_id) já significa "este plano tem acesso".
"""

import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class PlanFeature(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "plan_features"
    __table_args__ = (UniqueConstraint("plan_id", "feature_id", name="uq_plan_features_plan_feature"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("features.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quota_limit: Mapped[int | None] = mapped_column(Integer)

    plan: Mapped["Plan"] = relationship(back_populates="plan_features")
    feature: Mapped["Feature"] = relationship(back_populates="plan_features")