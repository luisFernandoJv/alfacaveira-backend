# app/repositories/learning/notebook_folder_repository.py
"""Repositório de acesso a dados de `NotebookFolder`."""

import uuid
from typing import Optional

from sqlalchemy import select, delete

from app.models.learning.notebook_folder import NotebookFolder
from app.repositories.base import BaseRepository


class NotebookFolderRepository(BaseRepository[NotebookFolder]):
    """Repositório de pastas de cadernos."""

    model = NotebookFolder

    async def get_owned(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> NotebookFolder | None:
        """Busca uma pasta restrita ao dono."""
        stmt = select(NotebookFolder).where(
            NotebookFolder.id == folder_id,
            NotebookFolder.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
    ) -> list[NotebookFolder]:
        """Lista todas as pastas do usuário, ordenadas por nome."""
        stmt = (
            select(NotebookFolder)
            .where(NotebookFolder.user_id == user_id)
            .order_by(NotebookFolder.name.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_children(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[NotebookFolder]:
        """Lista subpastas de uma pasta."""
        stmt = (
            select(NotebookFolder)
            .where(
                NotebookFolder.parent_id == folder_id,
                NotebookFolder.user_id == user_id,
            )
            .order_by(NotebookFolder.name.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(
        self,
        user_id: uuid.UUID,
        name: str,
    ) -> NotebookFolder | None:
        """Busca pasta por nome (exato)."""
        stmt = select(NotebookFolder).where(
            NotebookFolder.user_id == user_id,
            NotebookFolder.name == name,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_cascade(self, folder_id: uuid.UUID) -> None:
        """Exclui pasta e suas subpastas (CASCADE)."""
        stmt = delete(NotebookFolder).where(NotebookFolder.id == folder_id)
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_with_parents(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[NotebookFolder]:
        """Retorna a pasta e seus ancestrais (para breadcrumb)."""
        result: list[NotebookFolder] = []
        current_id = folder_id

        while current_id:
            folder = await self.get_owned(current_id, user_id)
            if not folder:
                break
            result.append(folder)
            current_id = folder.parent_id

        return list(reversed(result))