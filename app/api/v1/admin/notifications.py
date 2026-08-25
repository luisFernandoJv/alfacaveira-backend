"""Ferramentas administrativas de notificações."""

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import AsyncSessionFactory, get_db
from app.models.billing.plan import Plan
from app.models.billing.subscription import Subscription
from app.models.enums import SubscriptionStatus
from app.models.identity.user import User
from app.schemas.platform.notification import NotificationBroadcastRequest
from app.security.dependencies import CurrentAdminUser
from app.services.platform.notification_service import NotificationService

router = APIRouter()


async def _resolve_segment_user_ids(
    session: AsyncSession, segment: str
) -> list[uuid.UUID]:
    if segment == "free":
        stmt = (
            select(User.id)
            .outerjoin(
                Subscription,
                (Subscription.user_id == User.id)
                & (Subscription.status == SubscriptionStatus.ATIVA),
            )
            .where(User.is_active.is_(True), Subscription.id.is_(None))
        )
    elif segment in {"standard", "pro"}:
        stmt = (
            select(User.id)
            .join(
                Subscription,
                (Subscription.user_id == User.id)
                & (Subscription.status == SubscriptionStatus.ATIVA),
            )
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(User.is_active.is_(True), Plan.slug == segment)
        )
    else:
        stmt = select(User.id).where(User.is_active.is_(True))

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _run_broadcast(
    user_ids: Sequence[uuid.UUID],
    body: NotificationBroadcastRequest,
    batch_size: int = 100,
) -> None:
    """Worker leve: abre sessões próprias e nunca reutiliza a request."""
    for start in range(0, len(user_ids), batch_size):
        batch = list(user_ids[start : start + batch_size])
        async with AsyncSessionFactory() as session:
            service = NotificationService(session)
            await service.create_marketing_batch(
                user_ids=batch,
                title=body.title,
                body=body.body,
                link=body.link,
                payload={"broadcast": True, "segment": body.segment},
            )


@router.post("/broadcast", response_model=Envelope[dict])
async def broadcast_notification(
    body: NotificationBroadcastRequest,
    background_tasks: BackgroundTasks,
    _admin: CurrentAdminUser,
    session: AsyncSession = Depends(get_db),
) -> Envelope[dict]:
    user_ids = await _resolve_segment_user_ids(session, body.segment)
    background_tasks.add_task(_run_broadcast, user_ids, body)

    return Envelope(
        data={
            "queued": True,
            "targeted_users": len(user_ids),
            "segment": body.segment,
        }
    )
