"""Preferências de notificações da conta autenticada."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.models.enums import NOTIFICATION_MANDATORY_CATEGORIES
from app.schemas.platform.notification import (
    NotificationPreferencePatchItem,
    NotificationPreferenceResponse,
    NotificationPreferencesPatch,
)
from app.security.dependencies import CurrentUser
from app.services.platform.notification_preference_service import (
    NotificationPreferenceService,
)

router = APIRouter()


def get_preference_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationPreferenceService:
    return NotificationPreferenceService(session)


PreferenceServiceDep = Annotated[
    NotificationPreferenceService, Depends(get_preference_service)
]


def _response(item) -> NotificationPreferenceResponse:
    return NotificationPreferenceResponse(
        category=item.category,
        in_app_enabled=item.in_app_enabled,
        email_enabled=item.email_enabled,
        mandatory=item.category in NOTIFICATION_MANDATORY_CATEGORIES,
    )


@router.get(
    "/me/notification-preferences",
    response_model=Envelope[list[NotificationPreferenceResponse]],
)
async def get_notification_preferences(
    current_user: CurrentUser,
    service: PreferenceServiceDep,
) -> Envelope[list[NotificationPreferenceResponse]]:
    preferences = await service.list_preferences(current_user.id)
    return Envelope(data=[_response(item) for item in preferences])


@router.patch(
    "/me/notification-preferences",
    response_model=Envelope[list[NotificationPreferenceResponse]],
)
async def patch_notification_preferences(
    body: NotificationPreferencesPatch,
    current_user: CurrentUser,
    service: PreferenceServiceDep,
) -> Envelope[list[NotificationPreferenceResponse]]:
    updates = [
        (item.category, item.in_app_enabled, item.email_enabled)
        for item in body.preferences
    ]
    preferences = await service.update(current_user.id, updates)
    return Envelope(data=[_response(item) for item in preferences])
