"""Regras de negócio para preferências de notificação."""

import uuid
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.uow import UnitOfWork
from app.models.enums import (
    NOTIFICATION_MANDATORY_CATEGORIES,
    NotificationCategory,
)
from app.models.platform.notification_preference import NotificationPreference
from app.repositories.platform.notification_preference_repository import (
    NotificationPreferenceRepository,
)

ALL_CATEGORIES: tuple[NotificationCategory, ...] = tuple(NotificationCategory)


class NotificationPreferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._preferences = NotificationPreferenceRepository(session)

    @staticmethod
    def normalize(
        category: NotificationCategory,
        in_app_enabled: bool,
        email_enabled: bool,
    ) -> tuple[bool, bool]:
        if category in NOTIFICATION_MANDATORY_CATEGORIES:
            return True, True
        return in_app_enabled, email_enabled

    async def list_preferences(
        self, user_id: uuid.UUID
    ) -> list[NotificationPreference]:
        stored = {
            item.category: item for item in await self._preferences.list_by_user(user_id)
        }
        result: list[NotificationPreference] = []
        for category in ALL_CATEGORIES:
            item = stored.get(category)
            if item is None:
                in_app, email = self.normalize(category, True, True)
                item = NotificationPreference(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    category=category,
                    in_app_enabled=in_app,
                    email_enabled=email,
                )
            else:
                item.in_app_enabled, item.email_enabled = self.normalize(
                    category, item.in_app_enabled, item.email_enabled
                )
            result.append(item)
        return result

    async def get_preference(
        self, user_id: uuid.UUID, category: NotificationCategory
    ) -> tuple[bool, bool]:
        item = await self._preferences.get_by_user_category(user_id, category)
        if item is None:
            return self.normalize(category, True, True)
        return self.normalize(category, item.in_app_enabled, item.email_enabled)

    async def is_in_app_enabled(
        self, user_id: uuid.UUID, category: NotificationCategory
    ) -> bool:
        return (await self.get_preference(user_id, category))[0]

    async def is_email_enabled(
        self, user_id: uuid.UUID, category: NotificationCategory
    ) -> bool:
        return (await self.get_preference(user_id, category))[1]

    async def update(
        self,
        user_id: uuid.UUID,
        updates: Iterable[tuple[NotificationCategory, bool | None, bool | None]],
    ) -> list[NotificationPreference]:
        async with UnitOfWork(self._session):
            for category, in_app_enabled, email_enabled in updates:
                current = await self._preferences.get_by_user_category(user_id, category)
                current_in_app = current.in_app_enabled if current else True
                current_email = current.email_enabled if current else True
                in_app, email = self.normalize(
                    category,
                    current_in_app if in_app_enabled is None else in_app_enabled,
                    current_email if email_enabled is None else email_enabled,
                )
                await self._preferences.upsert(
                    user_id=user_id,
                    category=category,
                    in_app_enabled=in_app,
                    email_enabled=email,
                )
        return await self.list_preferences(user_id)
