# app/repositories/learning/notebook_repository.py
"""Repositório de acesso a dados de `Notebook`."""

import uuid
from typing import Optional

from sqlalchemy import select, func, or_, delete
from sqlalchemy.orm import selectinload

from app.models.content.question import Question
from app.models.learning.notebook import Notebook
from app.models.learning.notebook_question import NotebookQuestion
from app.repositories.base import BaseRepository

_RELATIONS = (
    selectinload(Notebook.folder),
    selectinload(Notebook.tags),
)

_QUESTION_DETAIL_RELATIONS = (
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question).selectinload(Question.discipline),
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question).selectinload(Question.subject),
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question).selectinload(Question.topic),
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question).selectinload(Question.exam_board),
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question).selectinload(Question.exam_edition),
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question).selectinload(Question.organization),
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question).selectinload(Question.tags),
    selectinload(Notebook.questions).selectinload(NotebookQuestion.question).selectinload(Question.attachments),
)


class NotebookRepository(BaseRepository[Notebook]):
    """Repositório de cadernos."""

    model = Notebook

    async def get_owned(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Notebook | None:
        """Busca um caderno restrito ao dono com relações carregadas."""
        stmt = (
            select(Notebook)
            .where(
                Notebook.id == notebook_id,
                Notebook.user_id == user_id,
            )
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_questions(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Notebook | None:
        """Busca um caderno com as questões (e suas relações) carregadas."""
        stmt = (
            select(Notebook)
            .where(
                Notebook.id == notebook_id,
                Notebook.user_id == user_id,
            )
            .options(*_RELATIONS, *_QUESTION_DETAIL_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        limit: int,
        cursor_id: Optional[uuid.UUID] = None,
        folder_id: Optional[uuid.UUID] = None,
        favorite: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Notebook], int]:
        """Lista cadernos do usuário com filtros."""
        stmt = (
            select(Notebook)
            .where(Notebook.user_id == user_id)
            .options(*_RELATIONS)
            .order_by(Notebook.created_at.desc(), Notebook.id.desc())
            .limit(limit)
        )

        if folder_id is not None:
            stmt = stmt.where(Notebook.folder_id == folder_id)

        if favorite is not None:
            stmt = stmt.where(Notebook.is_favorite == favorite)

        if search:
            search_term = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Notebook.name.ilike(search_term),
                    Notebook.description.ilike(search_term),
                )
            )

        if cursor_id is not None:
            cursor = await self.get_by_id(cursor_id)
            if cursor is not None:
                stmt = stmt.where(
                    (Notebook.created_at < cursor.created_at)
                    | (
                        (Notebook.created_at == cursor.created_at)
                        & (Notebook.id < cursor.id)
                    )
                )

        result = await self.session.execute(stmt)
        items = list(result.scalars().unique().all())

        # Contagem total
        count_stmt = select(func.count()).select_from(Notebook).where(Notebook.user_id == user_id)
        if folder_id is not None:
            count_stmt = count_stmt.where(Notebook.folder_id == folder_id)
        if favorite is not None:
            count_stmt = count_stmt.where(Notebook.is_favorite == favorite)
        if search:
            search_term = f"%{search}%"
            count_stmt = count_stmt.where(
                or_(
                    Notebook.name.ilike(search_term),
                    Notebook.description.ilike(search_term),
                )
            )

        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        return items, total

    async def count_questions(self, notebook_id: uuid.UUID) -> int:
        """Conta questões de um caderno."""
        stmt = select(func.count()).select_from(NotebookQuestion).where(
            NotebookQuestion.notebook_id == notebook_id
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_by_name(
        self,
        user_id: uuid.UUID,
        name: str,
    ) -> Notebook | None:
        """Busca caderno por nome (exato) para o usuário."""
        stmt = select(Notebook).where(
            Notebook.user_id == user_id,
            Notebook.name == name,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def toggle_favorite(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        is_favorite: bool,
    ) -> Notebook | None:
        """Alterna o estado de favorito."""
        notebook = await self.get_owned(notebook_id, user_id)
        if notebook:
            notebook.is_favorite = is_favorite
            await self.session.flush()
        return notebook

    async def delete(self, notebook_id: uuid.UUID) -> bool:
        """Remove um caderno do banco."""
        stmt = delete(Notebook).where(Notebook.id == notebook_id)
        result = await self.session.execute(stmt)
        return result.rowcount > 0