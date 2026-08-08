"""Endpoints HTTP de planos e do catálogo de features.

Leitura (`GET /plans`, `GET /plans/{id}`) é pública a qualquer usuário
autenticado ou visitante — é a vitrine de planos (tela de upgrade).
Escrita é toda restrita a administradores.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.models.enums import FeatureKey
from app.schemas.billing import (
    FeatureCreateRequest,
    FeatureResponse,
    PlanCreateRequest,
    PlanResponse,
    PlanUpdateRequest,
    SetPlanFeatureRequest,
)
from app.security.dependencies import CurrentAdminUser
from app.services.billing.plan_service import PlanService

router = APIRouter()


def get_plan_service(session: Annotated[AsyncSession, Depends(get_db)]) -> PlanService:
    return PlanService(session)


PlanServiceDep = Annotated[PlanService, Depends(get_plan_service)]


# --------------------------------------------------------------------- #
# Planos
# --------------------------------------------------------------------- #


@router.get("", response_model=Envelope[list[PlanResponse]])
async def list_plans(
    plan_service: PlanServiceDep,
) -> Envelope[list[PlanResponse]]:
    """Planos ativos, ordenados por preço — tabela pequena (FREE/STANDARD/PRO)."""
    plans = await plan_service.list_plans()
    return Envelope(data=[PlanResponse.model_validate(p) for p in plans])


@router.get("/{plan_id}", response_model=Envelope[PlanResponse])
async def get_plan(
    plan_id: uuid.UUID,
    plan_service: PlanServiceDep,
) -> Envelope[PlanResponse]:
    plan = await plan_service.get_plan(plan_id)
    return Envelope(data=PlanResponse.model_validate(plan))


@router.post("", response_model=Envelope[PlanResponse], status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: PlanCreateRequest,
    _admin: CurrentAdminUser,
    plan_service: PlanServiceDep,
) -> Envelope[PlanResponse]:
    plan = await plan_service.create_plan(
        name=body.name,
        slug=body.slug,
        price_cents=body.price_cents,
        billing_period=body.billing_period,
        is_active=body.is_active,
    )
    return Envelope(data=PlanResponse.model_validate(plan))


@router.patch("/{plan_id}", response_model=Envelope[PlanResponse])
async def update_plan(
    plan_id: uuid.UUID,
    body: PlanUpdateRequest,
    _admin: CurrentAdminUser,
    plan_service: PlanServiceDep,
) -> Envelope[PlanResponse]:
    plan = await plan_service.update_plan(
        plan_id,
        name=body.name,
        price_cents=body.price_cents,
        billing_period=body.billing_period,
        is_active=body.is_active,
    )
    return Envelope(data=PlanResponse.model_validate(plan))


@router.put("/{plan_id}/features", response_model=Envelope[PlanResponse])
async def set_plan_feature(
    plan_id: uuid.UUID,
    body: SetPlanFeatureRequest,
    _admin: CurrentAdminUser,
    plan_service: PlanServiceDep,
) -> Envelope[PlanResponse]:
    """Concede (ou atualiza a quota de) uma feature para o plano. Idempotente."""
    plan = await plan_service.set_plan_feature(
        plan_id=plan_id, feature_key=body.feature_key, quota_limit=body.quota_limit
    )
    return Envelope(data=PlanResponse.model_validate(plan))


@router.delete("/{plan_id}/features/{feature_key}", response_model=Envelope[PlanResponse])
async def remove_plan_feature(
    plan_id: uuid.UUID,
    feature_key: str,
    _admin: CurrentAdminUser,
    plan_service: PlanServiceDep,
) -> Envelope[PlanResponse]:
    plan = await plan_service.remove_plan_feature(
        plan_id=plan_id, feature_key=FeatureKey(feature_key)
    )
    return Envelope(data=PlanResponse.model_validate(plan))


# --------------------------------------------------------------------- #
# Catálogo de features (administrativo)
# --------------------------------------------------------------------- #


@router.get("/features/catalog", response_model=Envelope[list[FeatureResponse]])
async def list_features(
    _admin: CurrentAdminUser,
    plan_service: PlanServiceDep,
) -> Envelope[list[FeatureResponse]]:
    """Catálogo completo de features — administrativo."""
    features = await plan_service.list_features()
    return Envelope(data=[FeatureResponse.model_validate(f) for f in features])


@router.post(
    "/features/catalog",
    response_model=Envelope[FeatureResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_feature(
    body: FeatureCreateRequest,
    _admin: CurrentAdminUser,
    plan_service: PlanServiceDep,
) -> Envelope[FeatureResponse]:
    feature = await plan_service.create_feature(
        key=body.key,
        kind=body.kind,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
    )
    return Envelope(data=FeatureResponse.model_validate(feature))