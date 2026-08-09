"""Endpoint HTTP para receber a confirmação assíncrona de pagamento
(webhook) do provedor configurado em `PAYMENT_GATEWAY_DRIVER`.

Sem autenticação de usuário (`CurrentUser`) — quem chama isto é o provedor de
pagamento, não uma sessão de usuário logado. A segurança aqui é a assinatura
do payload, não um JWT.

ADR-016 (docs/DECISIONS.md): a verificação de assinatura e o parsing do
payload bruto de cada provedor (Stripe, Pagar.me, Mercado Pago...) para o
formato normalizado `WebhookEvent` são responsabilidade do driver
configurado (`app/services/billing/gateway.py::PaymentGateway.
parse_webhook_event`), não deste endpoint — este endpoint só repassa o
corpo bruto e os headers, e nunca conhece o formato de nenhum provedor
específico. `PaymentService` também não conhece; ele só recebe
`provider_payment_id` + `status` já extraídos.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.billing import PaymentResponse
from app.services.billing.gateway import PaymentGateway, get_payment_gateway
from app.services.billing.payment_service import PaymentService

router = APIRouter()


def get_payment_service(session: Annotated[AsyncSession, Depends(get_db)]) -> PaymentService:
    return PaymentService(session)


PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]
PaymentGatewayDep = Annotated[PaymentGateway, Depends(get_payment_gateway)]


@router.post("/payments", response_model=Envelope[PaymentResponse])
async def receive_payment_webhook(
    request: Request,
    payment_service: PaymentServiceDep,
    gateway: PaymentGatewayDep,
) -> Envelope[PaymentResponse]:
    raw_body = await request.body()
    event = await gateway.parse_webhook_event(raw_body=raw_body, headers=request.headers)

    payment = await payment_service.process_webhook_event(
        provider_payment_id=event.provider_payment_id, status=event.status
    )
    return Envelope(data=PaymentResponse.model_validate(payment))