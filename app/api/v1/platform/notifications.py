# app/api/v1/platform/notifications.py
"""Endpoints HTTP de notificações."""

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.schemas.platform.notification import (
    NotificationListResponse,
    NotificationMarkReadRequest,
    NotificationResponse,
)
from app.security.dependencies import CurrentUser
from app.services.platform.notification_service import NotificationService

router = APIRouter()


def get_notification_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationService:
    return NotificationService(session)


NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


@router.get("", response_model=Envelope[NotificationListResponse])
async def list_notifications(
    current_user: CurrentUser,
    notification_service: NotificationServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    status: Annotated[Optional[str], Query()] = None,
) -> Envelope[NotificationListResponse]:
    """Lista notificações do usuário."""
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    notifications, total, unread_count = await notification_service.list_notifications(
        user_id=current_user.id,
        limit=limit,
        cursor_id=cursor_id,
        status=status,
    )

    next_cursor = (
        CursorPage.encode_cursor(str(notifications[-1].id))
        if len(notifications) == limit
        else None
    )

    return Envelope(
        data=NotificationListResponse(
            items=[NotificationResponse.model_validate(n) for n in notifications],
            total=total,
            unread_count=unread_count,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )
    )


@router.get("/unread/count", response_model=Envelope[int])
async def get_unread_count(
    current_user: CurrentUser,
    notification_service: NotificationServiceDep,
) -> Envelope[int]:
    """Retorna a quantidade de notificações não lidas."""
    count = await notification_service.get_unread_count(current_user.id)
    return Envelope(data=count)


@router.post("/mark-read", response_model=Envelope[int])
async def mark_notifications_read(
    body: NotificationMarkReadRequest,
    current_user: CurrentUser,
    notification_service: NotificationServiceDep,
) -> Envelope[int]:
    """Marca notificações como lidas."""
    count = await notification_service.mark_as_read(
        user_id=current_user.id,
        notification_ids=body.notification_ids,
        mark_all=body.mark_all,
    )
    return Envelope(data=count)


@router.post("/{notification_id}/archive", response_model=Envelope[NotificationResponse])
async def archive_notification(
    notification_id: uuid.UUID,
    current_user: CurrentUser,
    notification_service: NotificationServiceDep,
) -> Envelope[NotificationResponse]:
    """Arquiva uma notificação."""
    notification = await notification_service.archive_notification(
        notification_id=notification_id,
        user_id=current_user.id,
    )
    return Envelope(data=NotificationResponse.model_validate(notification))