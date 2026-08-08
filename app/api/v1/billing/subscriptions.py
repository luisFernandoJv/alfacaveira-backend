"""Endpoints HTTP de assinaturas do usuário autenticado.

Tudo aqui é escopado ao dono (`current_user.id`) — `SubscriptionService` já
garante isso via `get_owned`/`get_active_by_user`/`get_subscription`. Não há
endpoint administrativo de listagem de todas as assinaturas nesta etapa
(fora de escopo; entraria como um módulo `admin` separado se necessário).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.billing import (
    CancelSubscriptionRequest,
    ChangePlanRequest,
    CreateSubscriptionRequest,
    PaymentResponse,
    PlanResponse,
    SubscriptionDetailResponse,
    SubscriptionResponse,
)
from app.security.dependencies import CurrentUser
from app.services.billing.feature_gate_service import FeatureGateService
from app.services.billing.payment_service import PaymentService
from app.services.billing.subscription_service import SubscriptionService

router = APIRouter()


def get_subscription_service(session: Annotated[AsyncSession, Depends(get_db)]) -> SubscriptionService:
    return SubscriptionService(session)


def get_payment_service(session: Annotated[AsyncSession, Depends(get_db)]) -> PaymentService:
    return PaymentService(session)


def get_feature_gate_service(session: Annotated[AsyncSession, Depends(get_db)]) -> FeatureGateService:
    return FeatureGateService(session)


SubscriptionServiceDep = Annotated[SubscriptionService, Depends(get_subscription_service)]
PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]
FeatureGateServiceDep = Annotated[FeatureGateService, Depends(get_feature_gate_service)]


# --------------------------------------------------------------------- #
# Plano efetivo do usuário (leitura via FeatureGateService)
# --------------------------------------------------------------------- #


@router.get("/me/plan", response_model=Envelope[PlanResponse])
async def get_my_effective_plan(
    current_user: CurrentUser,
    feature_gate_service: FeatureGateServiceDep,
) -> Envelope[PlanResponse]:
    """Plano efetivo do usuário: o da assinatura ativa, ou FREE quando não
    há uma. Único lugar do frontend que precisa saber "o que meu plano
    inclui" — não confundir com o catálogo administrativo em
    `GET /billing/plans/features/catalog`."""
    plan = await feature_gate_service.get_effective_plan(current_user.id)
    return Envelope(data=PlanResponse.model_validate(plan))


# --------------------------------------------------------------------- #
# Assinaturas
# --------------------------------------------------------------------- #


@router.get("", response_model=Envelope[list[SubscriptionResponse]])
async def list_my_subscriptions(
    current_user: CurrentUser,
    subscription_service: SubscriptionServiceDep,
) -> Envelope[list[SubscriptionResponse]]:
    """Histórico completo (ativas, canceladas, expiradas) do usuário —
    volume baixo por usuário, sem paginação cursor-based."""
    subscriptions = await subscription_service.list_subscriptions(current_user.id)
    return Envelope(data=[SubscriptionResponse.model_validate(s) for s in subscriptions])


@router.get("/{subscription_id}", response_model=Envelope[SubscriptionDetailResponse])
async def get_subscription(
    subscription_id: uuid.UUID,
    current_user: CurrentUser,
    subscription_service: SubscriptionServiceDep,
) -> Envelope[SubscriptionDetailResponse]:
    subscription = await subscription_service.get_subscription(subscription_id, current_user.id)
    return Envelope(data=SubscriptionDetailResponse.model_validate(subscription))


@router.post(
    "", response_model=Envelope[SubscriptionResponse], status_code=status.HTTP_201_CREATED
)
async def create_subscription(
    body: CreateSubscriptionRequest,
    current_user: CurrentUser,
    subscription_service: SubscriptionServiceDep,
) -> Envelope[SubscriptionResponse]:
    subscription = await subscription_service.create_subscription(current_user.id, body.plan_id)
    return Envelope(data=SubscriptionResponse.model_validate(subscription))


@router.post("/{subscription_id}/cancel", response_model=Envelope[SubscriptionResponse])
async def cancel_subscription(
    subscription_id: uuid.UUID,
    body: CancelSubscriptionRequest,
    current_user: CurrentUser,
    subscription_service: SubscriptionServiceDep,
) -> Envelope[SubscriptionResponse]:
    subscription = await subscription_service.cancel_subscription(
        subscription_id, current_user.id, immediately=body.immediately
    )
    return Envelope(data=SubscriptionResponse.model_validate(subscription))


@router.post("/{subscription_id}/reactivate", response_model=Envelope[SubscriptionResponse])
async def reactivate_subscription(
    subscription_id: uuid.UUID,
    current_user: CurrentUser,
    subscription_service: SubscriptionServiceDep,
) -> Envelope[SubscriptionResponse]:
    subscription = await subscription_service.reactivate_subscription(
        subscription_id, current_user.id
    )
    return Envelope(data=SubscriptionResponse.model_validate(subscription))


@router.post("/{subscription_id}/change-plan", response_model=Envelope[SubscriptionResponse])
async def change_plan(
    subscription_id: uuid.UUID,
    body: ChangePlanRequest,
    current_user: CurrentUser,
    subscription_service: SubscriptionServiceDep,
) -> Envelope[SubscriptionResponse]:
    subscription = await subscription_service.change_plan(
        subscription_id, current_user.id, body.new_plan_id
    )
    return Envelope(data=SubscriptionResponse.model_validate(subscription))


# --------------------------------------------------------------------- #
# Pagamentos de uma assinatura
# --------------------------------------------------------------------- #


@router.get("/{subscription_id}/payments", response_model=Envelope[list[PaymentResponse]])
async def list_subscription_payments(
    subscription_id: uuid.UUID,
    current_user: CurrentUser,
    subscription_service: SubscriptionServiceDep,
    payment_service: PaymentServiceDep,
) -> Envelope[list[PaymentResponse]]:
    # `PaymentService.list_by_subscription` não checa dono (não tem
    # `user_id`) — a posse é validada aqui via `get_subscription`, que
    # levanta `NotFoundError` se a assinatura não for do usuário autenticado.
    await subscription_service.get_subscription(subscription_id, current_user.id)
    payments = await payment_service.list_by_subscription(subscription_id)
    return Envelope(data=[PaymentResponse.model_validate(p) for p in payments])


@router.post(
    "/{subscription_id}/charge",
    response_model=Envelope[PaymentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def charge_subscription(
    subscription_id: uuid.UUID,
    current_user: CurrentUser,
    subscription_service: SubscriptionServiceDep,
    payment_service: PaymentServiceDep,
) -> Envelope[PaymentResponse]:
    """Inicia manualmente a cobrança do período corrente (ex.: retry após
    `INADIMPLENTE`). Mesma checagem de posse do endpoint de pagamentos acima."""
    await subscription_service.get_subscription(subscription_id, current_user.id)
    payment = await payment_service.charge_subscription(subscription_id)
    return Envelope(data=PaymentResponse.model_validate(payment))