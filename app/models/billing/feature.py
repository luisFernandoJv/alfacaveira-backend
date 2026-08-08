"""Feature: unidade de permissão que os planos agrupam.

Fonte de verdade administrável — `Plan.features` (JSONB) é um CACHE derivado
disto via `PlanFeature`, reconstruído por `PlanService` sempre que a
associação plano/feature muda. Módulos fora de `billing` nunca leem esta
tabela diretamente; sempre passam por `FeatureGateService`.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import FeatureKey, FeatureKind


class Feature(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "features"

    key: Mapped[FeatureKey] = mapped_column(
        PGEnum(
            FeatureKey,
            name="feature_key",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        unique=True,
        nullable=False,
        index=True,
    )
    kind: Mapped[FeatureKind] = mapped_column(
        PGEnum(
            FeatureKind,
            name="feature_kind",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    plan_features: Mapped[list["PlanFeature"]] = relationship(back_populates="feature")