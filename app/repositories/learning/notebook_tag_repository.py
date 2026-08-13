# app/repositories/learning/notebook_tag_repository.py
"""Repositório de acesso a dados de `NotebookTag`."""

import uuid

from sqlalchemy import select

from app.models.learning.notebook_tag import NotebookTag
from app.repositories.base import BaseRepository


class NotebookTagRepository(BaseRepository[NotebookTag]):
    """Repositório de tags de cadernos."""

    model = NotebookTag

    async def list_all(self) -> list[NotebookTag]:
        """Lista todas as tags, ordenadas por nome."""
        stmt = select(NotebookTag).order_by(NotebookTag.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> NotebookTag | None:
        """Busca tag por nome (exato)."""
        stmt = select(NotebookTag).where(NotebookTag.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> NotebookTag | None:
        """Busca tag por slug."""
        stmt = select(NotebookTag).where(NotebookTag.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_ids(self, tag_ids: list[uuid.UUID]) -> list[NotebookTag]:
        """Busca tags por lista de IDs."""
        if not tag_ids:
            return []
        stmt = select(NotebookTag).where(NotebookTag.id.in_(tag_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_or_create(self, name: str) -> NotebookTag:
        """Busca ou cria uma tag pelo nome."""
        existing = await self.get_by_name(name)
        if existing:
            return existing

        import re
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        tag = NotebookTag(name=name, slug=slug)
        self.session.add(tag)
        await self.session.flush()
        return tag