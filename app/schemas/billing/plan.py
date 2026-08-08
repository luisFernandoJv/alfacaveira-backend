"""Schemas de request/response de `Feature`, `Plan` e `PlanFeature`."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BillingPeriod, FeatureKey, FeatureKind


class FeatureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: FeatureKey
    kind: FeatureKind
    name: str
    description: str | None = None
    is_active: bool


class FeatureCreateRequest(BaseModel):
    key: FeatureKey
    kind: FeatureKind
    name: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class PlanFeatureResponse(BaseModel):
    """Uma linha da associação plano↔feature, com a feature embutida —
    é o que popula `PlanResponse.plan_features` (fonte de verdade
    normalizada; ver `Plan.features`, que é só o cache JSONB derivado)."""

    model_config = ConfigDict(from_attributes=True)

    feature: FeatureResponse
    quota_limit: int | None = None


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    price_cents: int
    billing_period: BillingPeriod
    is_active: bool
    plan_features: list[PlanFeatureResponse] = Field(default_factory=list)


class PlanCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=110, pattern=r"^[a-z0-9-]+$")
    price_cents: int = Field(ge=0)
    billing_period: BillingPeriod
    is_active: bool = True


class PlanUpdateRequest(BaseModel):
    """Todos os campos opcionais: PATCH parcial. `slug` não é editável (é o
    identificador estável usado por `FREE_PLAN_SLUG` e por integrações)."""

    name: str | None = Field(default=None, min_length=2, max_length=100)
    price_cents: int | None = Field(default=None, ge=0)
    billing_period: BillingPeriod | None = None
    is_active: bool | None = None


class SetPlanFeatureRequest(BaseModel):
    feature_key: FeatureKey
    quota_limit: int | None = Field(default=None, ge=0)