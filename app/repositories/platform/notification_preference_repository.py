"""Persistência das preferências de notificação."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.enums import NotificationCategory
from app.models.platform.notification_preference import NotificationPreference
from app.repositories.base import BaseRepository


class NotificationPreferenceRepository(BaseRepository[NotificationPreference]):
    model = NotificationPreference

    async def list_by_user(self, user_id: uuid.UUID) -> list[NotificationPreference]:
        stmt = (
            select(NotificationPreference)
            .where(NotificationPreference.user_id == user_id)
            .order_by(NotificationPreference.category.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_user_category(
        self, user_id: uuid.UUID, category: NotificationCategory
    ) -> NotificationPreference | None:
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        category: NotificationCategory,
        in_app_enabled: bool,
        email_enabled: bool,
    ) -> NotificationPreference:
        stmt = insert(NotificationPreference).values(
            id=uuid.uuid4(),
            user_id=user_id,
            category=category,
            in_app_enabled=in_app_enabled,
            email_enabled=email_enabled,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_notification_preferences_user_category",
            set_={
                "in_app_enabled": in_app_enabled,
                "email_enabled": email_enabled,
            },
        ).returning(NotificationPreference)
        result = await self.session.execute(stmt)
        return result.scalar_one()
