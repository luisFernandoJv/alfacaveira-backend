"""Schemas de request/response de `Payment` e do webhook de confirmação."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import PaymentStatus


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subscription_id: uuid.UUID
    amount_cents: int
    currency: str
    status: PaymentStatus
    provider: str | None
    provider_payment_id: str | None
    paid_at: datetime | None
    created_at: datetime


class PaymentWebhookEventRequest(BaseModel):
    """Corpo já normalizado do evento de webhook do provedor de pagamento.

    O formato bruto varia por provedor (Stripe, Pagar.me, Mercado Pago...);
    quando um provedor real for integrado, o parsing do payload dele para
    este formato acontece no próprio endpoint
    (`app/api/v1/billing/webhooks.py`), antes de chamar
    `PaymentService.process_webhook_event` — o service nunca conhece o
    formato específico de nenhum provedor.
    """

    provider_payment_id: str
    status: PaymentStatus