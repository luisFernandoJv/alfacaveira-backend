"""Schemas de request/response de `Subscription` e `SubscriptionHistory`."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SubscriptionHistoryReason, SubscriptionStatus
from app.schemas.billing.plan import PlanResponse


class SubscriptionHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_plan_id: uuid.UUID | None
    to_plan_id: uuid.UUID
    from_status: SubscriptionStatus | None
    to_status: SubscriptionStatus
    reason: SubscriptionHistoryReason
    created_at: datetime


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    status: SubscriptionStatus
    plan: PlanResponse
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    created_at: datetime


class SubscriptionDetailResponse(SubscriptionResponse):
    """Igual a `SubscriptionResponse`, com a trilha de auditoria embutida —
    usado no detalhe (`GET /subscriptions/{id}`), não na listagem."""

    history: list[SubscriptionHistoryResponse] = Field(default_factory=list)


class CreateSubscriptionRequest(BaseModel):
    plan_id: uuid.UUID


class ChangePlanRequest(BaseModel):
    new_plan_id: uuid.UUID


class CancelSubscriptionRequest(BaseModel):
    """`immediately=False` (padrão): agenda o cancelamento para o fim do
    período corrente (`cancel_at_period_end`). `immediately=True`: cancela
    na hora."""

    immediately: bool = False