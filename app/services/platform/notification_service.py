"""Serviço de notificações in-app."""

import uuid
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database.uow import UnitOfWork
from app.models.enums import NotificationCategory
from app.models.platform.notification import Notification
from app.repositories.platform.notification_repository import NotificationRepository
from app.services.platform.notification_preference_service import (
    NotificationPreferenceService,
)

logger = structlog.get_logger(__name__)


class NotificationService:
    """Cria e consulta notificações, aplicando preferências do usuário."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._notifications = NotificationRepository(session)
        self._preferences = NotificationPreferenceService(session)

    async def create_notification(
        self,
        user_id: uuid.UUID,
        type: str,
        title: str,
        body: str,
        link: Optional[str] = None,
        payload: Optional[dict] = None,
        category: NotificationCategory = NotificationCategory.SYSTEM,
    ) -> Notification | None:
        if not await self._preferences.is_in_app_enabled(user_id, category):
            logger.info(
                "notification.skipped_by_preference",
                user_id=str(user_id),
                notification_type=type,
                notification_category=category.value,
            )
            return None

        notification = Notification(
            user_id=user_id,
            type=type,
            category=category,
            title=title,
            body=body,
            link=link,
            status="unread",
            payload=payload or {},
        )
        try:
            async with UnitOfWork(self._session):
                await self._notifications.add(notification)
                await self._session.flush()
                await self._session.refresh(notification)
            return notification
        except Exception:
            logger.exception(
                "notification.create_failed",
                user_id=str(user_id),
                notification_type=type,
                notification_category=category.value,
            )
            raise

    async def list_notifications(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
        cursor_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        category: NotificationCategory | None = None,
    ) -> tuple[list[Notification], int, int]:
        notifications = await self._notifications.list_by_user(
            user_id=user_id,
            limit=limit,
            cursor_id=cursor_id,
            status=status,
            category=category,
        )
        total = await self._notifications.count_by_user(
            user_id, status=status, category=category
        )
        unread_count = await self._notifications.count_unread(user_id)
        return notifications, total, unread_count

    async def is_email_enabled(
        self, user_id: uuid.UUID, category: NotificationCategory
    ) -> bool:
        return await self._preferences.is_email_enabled(user_id, category)

    async def get_unread_count(self, user_id: uuid.UUID) -> int:
        return await self._notifications.count_unread(user_id)

    async def mark_as_read(
        self,
        user_id: uuid.UUID,
        notification_ids: Optional[list[uuid.UUID]] = None,
        mark_all: bool = False,
    ) -> int:
        async with UnitOfWork(self._session):
            if mark_all:
                return await self._notifications.mark_all_as_read(user_id)
            if notification_ids:
                return await self._notifications.mark_as_read(
                    user_id, notification_ids
                )
            return 0

    async def archive_notification(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> Notification:
        notification = await self._notifications.get_owned(notification_id, user_id)
        if not notification:
            raise NotFoundError("Notificação não encontrada.")
        notification.status = "archived"
        async with UnitOfWork(self._session):
            await self._session.flush()
        return notification

    async def archive_notifications(
        self, notification_ids: list[uuid.UUID], user_id: uuid.UUID
    ) -> int:
        if not notification_ids:
            return 0
        count = await self._notifications.archive_many(user_id, notification_ids)
        async with UnitOfWork(self._session):
            await self._session.flush()
        return count

    async def notify_new_comment(
        self,
        question_id: uuid.UUID,
        comment_id: uuid.UUID,
        comment_author_id: uuid.UUID,
        question_author_id: uuid.UUID,
        comment_content: str,
    ) -> None:
        if comment_author_id == question_author_id:
            return
        await self.create_notification(
            user_id=question_author_id,
            type="new_comment",
            title="Novo comentário na sua questão",
            body=f"Alguém comentou na sua questão: {comment_content[:100]}",
            link=f"/questoes?question={question_id}#comment-{comment_id}",
            payload={"question_id": str(question_id), "comment_id": str(comment_id), "author_id": str(comment_author_id)},
            category=NotificationCategory.COMMENT,
        )

    async def notify_new_reply(
        self,
        parent_comment_id: uuid.UUID,
        reply_id: uuid.UUID,
        reply_author_id: uuid.UUID,
        parent_author_id: uuid.UUID,
        reply_content: str,
    ) -> None:
        if reply_author_id == parent_author_id:
            return
        await self.create_notification(
            user_id=parent_author_id,
            type="new_reply",
            title="Nova resposta ao seu comentário",
            body=f"Alguém respondeu ao seu comentário: {reply_content[:100]}",
            link=f"/comentarios?question={parent_comment_id}#reply-{reply_id}",
            payload={"parent_comment_id": str(parent_comment_id), "reply_id": str(reply_id), "author_id": str(reply_author_id)},
            category=NotificationCategory.COMMENT,
        )

    async def notify_comment_vote(
        self,
        comment_id: uuid.UUID,
        voter_id: uuid.UUID,
        comment_author_id: uuid.UUID,
        vote_type: str,
    ) -> None:
        if voter_id == comment_author_id:
            return
        vote_emoji = "👍" if vote_type == "up" else "👎"
        await self.create_notification(
            user_id=comment_author_id,
            type="comment_vote",
            title=f"Alguém votou no seu comentário ({vote_emoji})",
            body=f"Um usuário votou {vote_type} no seu comentário.",
            link=f"/comentarios?question={comment_id}",
            payload={"comment_id": str(comment_id), "voter_id": str(voter_id), "vote_type": vote_type},
            category=NotificationCategory.COMMENT,
        )

    async def notify_plan_granted(
        self, user_id: uuid.UUID, plan_name: str, subscription_id: uuid.UUID | None = None
    ) -> None:
        try:
            await self.create_notification(
                user_id=user_id,
                type="plan_granted",
                title="Acesso ao plano concedido",
                body=f"Você ganhou acesso ao plano {plan_name}.",
                link="/plano",
                payload={
                    "plan_name": plan_name,
                    "subscription_id": str(subscription_id) if subscription_id else None,
                },
                category=NotificationCategory.PLAN,
            )
        except Exception as exc:
            logger.error(
                "notification.plan_granted_failed",
                user_id=str(user_id),
                error=str(exc),
            )

    async def notify_plan_revoked(
        self, user_id: uuid.UUID, plan_name: str | None = None
    ) -> None:
        plan_text = f" ({plan_name})" if plan_name else ""
        try:
            await self.create_notification(
                user_id=user_id,
                type="plan_revoked",
                title="Acesso ao plano revogado",
                body=f"O acesso ao seu plano{plan_text} foi encerrado.",
                link="/plano",
                payload={"plan_name": plan_name},
                category=NotificationCategory.PLAN,
            )
        except Exception as exc:
            logger.error(
                "notification.plan_revoked_failed",
                user_id=str(user_id),
                error=str(exc),
            )

    async def notify_billing_event(
        self, *, user_id: uuid.UUID, event_type: str, title: str, body: str,
        link: str = "/plano", payload: dict | None = None,
    ) -> None:
        await self.create_notification(
            user_id=user_id, type=event_type, title=title, body=body, link=link,
            payload=payload, category=NotificationCategory.BILLING,
        )

    async def create_marketing_batch(
        self,
        *,
        user_ids: list[uuid.UUID],
        title: str,
        body: str,
        link: str | None = None,
        payload: dict | None = None,
    ) -> int:
        """Cria marketing in-app em lote, respeitando preferências."""
        if not user_ids:
            return 0

        from sqlalchemy import select
        from app.models.platform.notification_preference import NotificationPreference

        stored = await self._session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id.in_(user_ids),
                NotificationPreference.category == NotificationCategory.MARKETING,
            )
        )
        preference_by_user = {
            row.user_id: row for row in stored.scalars().all()
        }

        notifications = []
        for user_id in user_ids:
            preference = preference_by_user.get(user_id)
            if preference is not None and not preference.in_app_enabled:
                continue
            notifications.append(
                Notification(
                    user_id=user_id,
                    type="marketing",
                    category=NotificationCategory.MARKETING,
                    title=title,
                    body=body,
                    link=link,
                    status="unread",
                    payload=payload or {},
                )
            )

        if not notifications:
            return 0

        try:
            async with UnitOfWork(self._session):
                self._session.add_all(notifications)
                await self._session.flush()
            return len(notifications)
        except Exception:
            logger.exception(
                "notification.marketing_batch_failed",
                requested_users=len(user_ids),
            )
            raise

    async def notify_marketing(
        self, *, user_id: uuid.UUID, title: str, body: str,
        link: str | None = None, payload: dict | None = None,
    ) -> None:
        await self.create_notification(
            user_id=user_id, type="marketing", title=title, body=body, link=link,
            payload=payload, category=NotificationCategory.MARKETING,
        )
