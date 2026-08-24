import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.models.billing.plan import Plan
from app.models.billing.subscription import Subscription
from app.models.enums import SubscriptionStatus
from app.schemas.billing.subscription import (
    AdminGrantSubscriptionRequest,
    SubscriptionResponse,
)
from app.schemas.identity.user import AdminUserListItem
from app.security.dependencies import CurrentAdminUser
from app.services.billing.subscription_service import SubscriptionService
from app.services.identity.user_service import UserService
from sqlalchemy import select
from app.models.identity.user import User

router = APIRouter()

@router.get("/users", response_model=Envelope[list[AdminUserListItem]])
async def list_users_admin(
    admin: CurrentAdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> Envelope[list[AdminUserListItem]]:
    user_service = UserService(session)
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    # Nota: UserService.list_users não tem filtro por is_active, vamos adicionar.
    # Por simplicidade, vou usar diretamente o repositório.
    from app.repositories.identity.user_repository import UserRepository
    repo = UserRepository(session)

    # Construir query com filtro
    stmt = select(User).order_by(User.created_at.asc(), User.id.asc()).limit(limit)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if cursor_id:
        cursor_user = await repo.get_by_id(cursor_id)
        if cursor_user:
            stmt = stmt.where(
                (User.created_at > cursor_user.created_at) |
                ((User.created_at == cursor_user.created_at) & (User.id > cursor_user.id))
            )
    result = await session.execute(stmt)
    users = list(result.scalars().all())
    next_cursor = CursorPage.encode_cursor(str(users[-1].id)) if len(users) == limit else None

    # Plano da assinatura ATIVA de cada usuário desta página, numa única
    # query (evita N+1). Usuário sem entrada aqui está no plano FREE.
    plan_by_user: dict[uuid.UUID, tuple[str, str]] = {}
    if users:
        plan_stmt = (
            select(Subscription.user_id, Plan.slug, Plan.name)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.user_id.in_([u.id for u in users]),
                Subscription.status == SubscriptionStatus.ATIVA,
            )
        )
        plan_result = await session.execute(plan_stmt)
        plan_by_user = {row.user_id: (row.slug, row.name) for row in plan_result}

    data: list[AdminUserListItem] = []
    for u in users:
        item = AdminUserListItem.model_validate(u)
        plan = plan_by_user.get(u.id)
        if plan:
            item.plan_slug, item.plan_name = plan
        data.append(item)

    return Envelope(
        data=data,
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )


@router.post(
    "/users/{user_id}/grant-subscription",
    response_model=Envelope[SubscriptionResponse],
)
async def grant_subscription_admin(
    user_id: uuid.UUID,
    body: AdminGrantSubscriptionRequest,
    admin: CurrentAdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[SubscriptionResponse]:
    """Concede acesso a um plano diretamente a um usuário, sem cobrança.

    Uso administrativo (parcerias, cortesias, suporte) — cancela qualquer
    assinatura ativa/pendente existente do usuário e cria uma nova já
    ATIVA. Ver `SubscriptionService.admin_grant_subscription`.
    """
    subscription_service = SubscriptionService(session)
    subscription = await subscription_service.admin_grant_subscription(
        admin_id=admin.id,
        user_id=user_id,
        plan_id=body.plan_id,
        duration_days=body.duration_days,
    )
    return Envelope(data=SubscriptionResponse.model_validate(subscription))


@router.delete(
    "/users/{user_id}/grant-subscription",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_subscription_admin(
    user_id: uuid.UUID,
    admin: CurrentAdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoga (cancela imediatamente) o acesso concedido manualmente a um
    usuário. Sem efeito se ele não tiver assinatura ativa."""
    subscription_service = SubscriptionService(session)
    await subscription_service.admin_revoke_subscription(
        admin_id=admin.id, user_id=user_id
    )