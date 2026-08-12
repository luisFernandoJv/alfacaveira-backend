# app/repositories/content/notebook_repository.py
"""Repositório de acesso a dados de notebooks."""

import uuid
from typing import Optional

from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload

from app.models.content.notebook import Notebook, NotebookQuestion, NotebookFolder, NotebookTag
from app.repositories.base import BaseRepository

_RELATIONS = (
    selectinload(Notebook.folder),
    selectinload(Notebook.tags),
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question),
)


class NotebookRepository(BaseRepository[Notebook]):
    model = Notebook

    async def get_with_relations(self, notebook_id: uuid.UUID) -> Notebook | None:
        stmt = select(Notebook).where(Notebook.id == notebook_id).options(*_RELATIONS)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned(self, notebook_id: uuid.UUID, user_id: uuid.UUID) -> Notebook | None:
        stmt = (
            select(Notebook)
            .where(Notebook.id == notebook_id, Notebook.user_id == user_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
        cursor_id: Optional[uuid.UUID] = None,
        folder_id: Optional[uuid.UUID] = None,
        is_favorite: Optional[bool] = None,
        tag_id: Optional[uuid.UUID] = None,
        search: Optional[str] = None,
    ) -> list[Notebook]:
        stmt = select(Notebook).where(Notebook.user_id == user_id).options(*_RELATIONS)

        if folder_id is not None:
            stmt = stmt.where(Notebook.folder_id == folder_id)
        if is_favorite is not None:
            stmt = stmt.where(Notebook.is_favorite == is_favorite)
        if tag_id is not None:
            stmt = stmt.where(Notebook.tags.any(id=tag_id))
        if search:
            stmt = stmt.where(
                Notebook.name.ilike(f"%{search}%")
                | Notebook.description.ilike(f"%{search}%")
            )

        stmt = stmt.order_by(Notebook.is_favorite.desc(), Notebook.created_at.desc()).limit(limit)

        if cursor_id:
            cursor = await self.get_by_id(cursor_id)
            if cursor:
                stmt = stmt.where(
                    (Notebook.created_at < cursor.created_at)
                    | ((Notebook.created_at == cursor.created_at) & (Notebook.id < cursor.id))
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def count_by_user(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Notebook).where(Notebook.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def add_question(
        self,
        notebook_id: uuid.UUID,
        question_id: uuid.UUID,
        note: str | None = None,
    ) -> NotebookQuestion:
        notebook_question = NotebookQuestion(
            notebook_id=notebook_id,
            question_id=question_id,
            note=note,
        )
        self.session.add(notebook_question)
        await self.session.flush()
        return notebook_question

    async def remove_question(self, notebook_id: uuid.UUID, question_id: uuid.UUID) -> bool:
        stmt = delete(NotebookQuestion).where(
            NotebookQuestion.notebook_id == notebook_id,
            NotebookQuestion.question_id == question_id,
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def get_question(self, notebook_id: uuid.UUID, question_id: uuid.UUID) -> NotebookQuestion | None:
        stmt = select(NotebookQuestion).where(
            NotebookQuestion.notebook_id == notebook_id,
            NotebookQuestion.question_id == question_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class NotebookFolderRepository(BaseRepository[NotebookFolder]):
    model = NotebookFolder

    async def list_by_user(self, user_id: uuid.UUID) -> list[NotebookFolder]:
        stmt = select(NotebookFolder).where(NotebookFolder.user_id == user_id).order_by(NotebookFolder.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_owned(self, folder_id: uuid.UUID, user_id: uuid.UUID) -> NotebookFolder | None:
        stmt = select(NotebookFolder).where(NotebookFolder.id == folder_id, NotebookFolder.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_parents(self, folder_id: uuid.UUID, user_id: uuid.UUID) -> NotebookFolder | None:
        stmt = (
            select(NotebookFolder)
            .where(NotebookFolder.id == folder_id, NotebookFolder.user_id == user_id)
            .options(selectinload(NotebookFolder.parent))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class NotebookTagRepository(BaseRepository[NotebookTag]):
    model = NotebookTag

    async def list_by_user(self, user_id: uuid.UUID) -> list[NotebookTag]:
        stmt = select(NotebookTag).where(NotebookTag.user_id == user_id).order_by(NotebookTag.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_slug(self, user_id: uuid.UUID, slug: str) -> NotebookTag | None:
        stmt = select(NotebookTag).where(NotebookTag.user_id == user_id, NotebookTag.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned(self, tag_id: uuid.UUID, user_id: uuid.UUID) -> NotebookTag | None:
        stmt = select(NotebookTag).where(NotebookTag.id == tag_id, NotebookTag.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()