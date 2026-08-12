# app/services/platform/notification_service.py
"""Serviço de notificações."""

import uuid
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database.uow import UnitOfWork
from app.models.platform.notification import Notification
from app.repositories.platform.notification_repository import NotificationRepository


class NotificationService:
    """Serviço de notificações."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._notifications = NotificationRepository(session)

    # ==================================================================== #
    # Criação
    # ==================================================================== #

    async def create_notification(
        self,
        user_id: uuid.UUID,
        type: str,
        title: str,
        body: str,
        link: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> Notification:
        """Cria uma nova notificação."""
        try:
            notification = Notification(
                user_id=user_id,
                type=type,
                title=title,
                body=body,
                link=link,
                status="unread",
                payload=payload or {},
            )

            async with UnitOfWork(self._session):
                await self._notifications.add(notification)
                await self._session.flush()
                await self._session.refresh(notification)

            return notification
        except Exception as e:
            print(f"[Notification] Erro ao criar notificação: {e}")
            # Retornar um objeto vazio para não quebrar o fluxo
            return Notification(
                id=uuid.uuid4(),
                user_id=user_id,
                type=type,
                title=title,
                body=body,
                link=link,
                status="unread",
                payload=payload or {},
            )

    # ==================================================================== #
    # Leitura
    # ==================================================================== #

    async def list_notifications(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
        cursor_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
    ) -> tuple[List[Notification], int, int]:
        """Lista notificações do usuário."""
        notifications = await self._notifications.list_by_user(
            user_id=user_id,
            limit=limit,
            cursor_id=cursor_id,
            status=status,
        )
        total = await self._notifications.count_by_user(user_id)
        unread_count = await self._notifications.count_unread(user_id)

        return notifications, total, unread_count

    async def get_unread_count(self, user_id: uuid.UUID) -> int:
        """Retorna a quantidade de notificações não lidas."""
        return await self._notifications.count_unread(user_id)

    # ==================================================================== #
    # Ações
    # ==================================================================== #

    async def mark_as_read(
        self,
        user_id: uuid.UUID,
        notification_ids: Optional[List[uuid.UUID]] = None,
        mark_all: bool = False,
    ) -> int:
        """Marca notificações como lidas."""
        if mark_all:
            count = await self._notifications.mark_all_as_read(user_id)
        elif notification_ids:
            count = await self._notifications.mark_as_read(user_id, notification_ids)
        else:
            count = 0

        return count

    async def archive_notification(
        self,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Notification:
        """Arquiva uma notificação."""
        notification = await self._notifications.get_owned(notification_id, user_id)
        if not notification:
            raise NotFoundError("Notificação não encontrada.")

        notification.status = "archived"

        async with UnitOfWork(self._session):
            await self._session.flush()

        return notification

    # ==================================================================== #
    # Eventos (gatilhos)
    # ==================================================================== #

    async def notify_new_comment(
        self,
        question_id: uuid.UUID,
        comment_id: uuid.UUID,
        comment_author_id: uuid.UUID,
        question_author_id: uuid.UUID,
        comment_content: str,
    ) -> None:
        """Notifica o autor da questão sobre um novo comentário."""
        if comment_author_id == question_author_id:
            return

        try:
            await self.create_notification(
                user_id=question_author_id,
                type="new_comment",
                title="Novo comentário na sua questão",
                body=f"Alguém comentou na sua questão: {comment_content[:100]}...",
                link=f"/questoes?question={question_id}#comment-{comment_id}",
                payload={
                    "question_id": str(question_id),
                    "comment_id": str(comment_id),
                    "author_id": str(comment_author_id),
                },
            )
        except Exception as e:
            print(f"[Notification] Erro ao notificar novo comentário: {e}")

    async def notify_new_reply(
        self,
        parent_comment_id: uuid.UUID,
        reply_id: uuid.UUID,
        reply_author_id: uuid.UUID,
        parent_author_id: uuid.UUID,
        reply_content: str,
    ) -> None:
        """Notifica o autor do comentário sobre uma nova resposta."""
        if reply_author_id == parent_author_id:
            return

        try:
            await self.create_notification(
                user_id=parent_author_id,
                type="new_reply",
                title="Nova resposta ao seu comentário",
                body=f"Alguém respondeu ao seu comentário: {reply_content[:100]}...",
                link=f"/comentarios?question={parent_comment_id}#reply-{reply_id}",
                payload={
                    "parent_comment_id": str(parent_comment_id),
                    "reply_id": str(reply_id),
                    "author_id": str(reply_author_id),
                },
            )
        except Exception as e:
            print(f"[Notification] Erro ao notificar nova resposta: {e}")

    async def notify_comment_vote(
        self,
        comment_id: uuid.UUID,
        voter_id: uuid.UUID,
        comment_author_id: uuid.UUID,
        vote_type: str,
    ) -> None:
        """Notifica o autor do comentário sobre um voto."""
        if voter_id == comment_author_id:
            return

        try:
            vote_emoji = "👍" if vote_type == "up" else "👎"
            await self.create_notification(
                user_id=comment_author_id,
                type="comment_vote",
                title=f"Alguém votou no seu comentário ({vote_emoji})",
                body=f"Um usuário votou {vote_type} no seu comentário.",
                link=f"/comentarios?question={comment_id}",
                payload={
                    "comment_id": str(comment_id),
                    "voter_id": str(voter_id),
                    "vote_type": vote_type,
                },
            )
        except Exception as e:
            print(f"[Notification] Erro ao notificar voto: {e}")