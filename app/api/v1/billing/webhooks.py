"""Endpoint HTTP para receber a confirmação assíncrona de pagamento
(webhook) do provedor configurado em `PAYMENT_GATEWAY_DRIVER`.

Sem autenticação de usuário (`CurrentUser`) — quem chama isto é o provedor de
pagamento, não uma sessão de usuário logado. A segurança aqui é a assinatura
do payload, não um JWT.

O parsing do payload bruto de cada provedor (Stripe, Pagar.me, Mercado
Pago...) para o formato normalizado `PaymentWebhookEventRequest` é
responsabilidade deste endpoint — `PaymentService` nunca conhece o formato
de nenhum provedor específico. Hoje só existe o driver `console`
(`app/services/billing/gateway.py`), que não assina nada de verdade; por
isso a checagem de assinatura abaixo é condicionada a `PAYMENT_WEBHOOK_SECRET`
estar configurado.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.billing import PaymentResponse, PaymentWebhookEventRequest
from app.services.billing.payment_service import PaymentService

router = APIRouter()


def get_payment_service(session: Annotated[AsyncSession, Depends(get_db)]) -> PaymentService:
    return PaymentService(session)


PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]


def _verify_signature(signature: str | None) -> None:
    """Compara o header `X-Webhook-Signature` com `PAYMENT_WEBHOOK_SECRET`
    usando comparação de tempo constante (evita timing attack).

    Se `PAYMENT_WEBHOOK_SECRET` não estiver configurado (padrão em
    desenvolvimento, driver `console`), a checagem é pulada de propósito —
    não há segredo real para validar contra. Configurar a variável de
    ambiente ao integrar um provedor real passa a exigir a assinatura.
    """
    if not settings.PAYMENT_WEBHOOK_SECRET:
        return
    if signature is None or not hmac.compare_digest(signature, settings.PAYMENT_WEBHOOK_SECRET):
        raise UnauthorizedError("Assinatura do webhook inválida.")


@router.post("/payments", response_model=Envelope[PaymentResponse])
async def receive_payment_webhook(
    body: PaymentWebhookEventRequest,
    payment_service: PaymentServiceDep,
    x_webhook_signature: Annotated[str | None, Header()] = None,
) -> Envelope[PaymentResponse]:
    _verify_signature(x_webhook_signature)

    payment = await payment_service.process_webhook_event(
        provider_payment_id=body.provider_payment_id, status=body.status
    )
    return Envelope(data=PaymentResponse.model_validate(payment))