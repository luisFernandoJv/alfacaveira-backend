# app/repositories/platform/notification_repository.py
"""Repositório de notificações.

🔥 CORREÇÃO: os métodos abaixo tinham `except Exception: print(...); return
[]/0/None` em toda consulta. Isso faz qualquer erro real de banco (schema
desatualizado, coluna faltando, timeout, etc.) virar silenciosamente "sem
notificações" para o usuário, sem nunca aparecer como erro em lugar nenhum
observável (o `print()` some no stdout do processo, sem structlog, sem
traceback). Foi exatamente esse tipo de erro escondido que motivou a
migration `0019_fix_notifications_schema` (coluna `link` inexistente) —
e o padrão continuava aqui, pronto para esconder o próximo bug do mesmo
jeito.

A API já tem um handler genérico em `app/core/exceptions.py`
(`unhandled_exception_handler`) que loga o traceback completo via structlog
e devolve um 500 padronizado para o cliente. Deixar a exceção subir até ali
é estritamente melhor do que fingir sucesso com dado vazio: o time vê o
erro real nos logs, e o frontend recebe um erro de verdade (que já sabe
exibir, ver `AppTopbar` → estado `error`) em vez de uma lista vazia
enganosa.
"""

import uuid
from datetime import datetime, UTC
from typing import Optional, List

from sqlalchemy import select, update, func

from app.models.platform.notification import Notification
from app.models.enums import NotificationCategory
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    """Repositório de notificações."""

    model = Notification

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
        cursor_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        category: NotificationCategory | None = None,
    ) -> List[Notification]:
        """Lista notificações de um usuário."""
        stmt = select(Notification).where(Notification.user_id == user_id)

        if status:
            stmt = stmt.where(Notification.status == status)
        if category:
            stmt = stmt.where(Notification.category == category)

        stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)

        if cursor_id:
            cursor = await self.get_by_id(cursor_id)
            if cursor:
                stmt = stmt.where(
                    (Notification.created_at < cursor.created_at) |
                    ((Notification.created_at == cursor.created_at) &
                     (Notification.id < cursor.id))
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def count_by_user(
        self,
        user_id: uuid.UUID,
        *,
        status: Optional[str] = None,
        category: NotificationCategory | None = None,
    ) -> int:
        """Conta notificações do usuário respeitando os filtros."""
        stmt = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id
        )
        if status:
            stmt = stmt.where(Notification.status == status)
        if category:
            stmt = stmt.where(Notification.category == category)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_unread(self, user_id: uuid.UUID) -> int:
        """Conta notificações não lidas de um usuário."""
        stmt = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id,
            Notification.status == "unread",
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def mark_as_read(
        self,
        user_id: uuid.UUID,
        notification_ids: List[uuid.UUID],
    ) -> int:
        """Marca notificações específicas como lidas."""
        now = datetime.now(UTC)
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.id.in_(notification_ids),
                Notification.status == "unread",
            )
            .values(status="read", read_at=now)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def mark_all_as_read(self, user_id: uuid.UUID) -> int:
        """Marca todas as notificações de um usuário como lidas."""
        now = datetime.now(UTC)
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.status == "unread",
            )
            .values(status="read", read_at=now)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def get_owned(
        self,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[Notification]:
        """Busca uma notificação restrita ao dono."""
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def archive_many(
        self,
        user_id: uuid.UUID,
        notification_ids: List[uuid.UUID],
    ) -> int:
        """Arquiva em lote apenas notificações pertencentes ao usuário."""
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.id.in_(notification_ids),
                Notification.status != "archived",
            )
            .values(status="archived")
        )
        result = await self.session.execute(stmt)
        return result.rowcount
