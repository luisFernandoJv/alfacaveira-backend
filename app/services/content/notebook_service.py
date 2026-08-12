# app/services/content/notebook_service.py
"""Regras de negócio de cadernos (notebooks)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.content.notebook import Notebook, NotebookFolder, NotebookTag, NotebookQuestion
from app.repositories.content.notebook_repository import (
    NotebookRepository,
    NotebookFolderRepository,
    NotebookTagRepository,
)
from app.repositories.content.question_repository import QuestionRepository


class NotebookService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._notebooks = NotebookRepository(session)
        self._folders = NotebookFolderRepository(session)
        self._tags = NotebookTagRepository(session)
        self._questions = QuestionRepository(session)

    # ==================================================================== #
    # LEITURA
    # ==================================================================== #

    async def get_notebook(self, notebook_id: uuid.UUID, user_id: uuid.UUID) -> Notebook:
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if notebook is None:
            raise NotFoundError("Caderno não encontrado.")
        return notebook

    async def list_notebooks(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
        cursor_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
        is_favorite: bool | None = None,
        tag_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> list[Notebook]:
        return await self._notebooks.list_by_user(
            user_id=user_id,
            limit=limit,
            cursor_id=cursor_id,
            folder_id=folder_id,
            is_favorite=is_favorite,
            tag_id=tag_id,
            search=search,
        )

    async def get_folders(self, user_id: uuid.UUID) -> list[NotebookFolder]:
        return await self._folders.list_by_user(user_id)

    async def get_tags(self, user_id: uuid.UUID) -> list[NotebookTag]:
        return await self._tags.list_by_user(user_id)

    # ==================================================================== #
    # ESCRITA — Cadernos
    # ==================================================================== #

    async def create_notebook(
        self,
        user_id: uuid.UUID,
        name: str,
        description: str | None = None,
        folder_id: uuid.UUID | None = None,
        tag_ids: list[uuid.UUID] | None = None,
    ) -> Notebook:
        if folder_id is not None:
            folder = await self._folders.get_owned(folder_id, user_id)
            if folder is None:
                raise NotFoundError("Pasta não encontrada.")

        tags = []
        if tag_ids:
            for tag_id in tag_ids:
                tag = await self._tags.get_owned(tag_id, user_id)
                if tag is None:
                    raise NotFoundError(f"Tag {tag_id} não encontrada.")
                tags.append(tag)

        notebook = Notebook(
            user_id=user_id,
            name=name,
            description=description,
            folder_id=folder_id,
            tags=tags,
        )

        async with UnitOfWork(self._session):
            await self._notebooks.add(notebook)

        return await self._notebooks.get_with_relations(notebook.id)

    async def update_notebook(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        is_favorite: bool | None = None,
        folder_id: uuid.UUID | None = None,
        tag_ids: list[uuid.UUID] | None = None,
    ) -> Notebook:
        notebook = await self.get_notebook(notebook_id, user_id)

        if folder_id is not None:
            if folder_id == notebook.folder_id:
                pass
            else:
                folder = await self._folders.get_owned(folder_id, user_id)
                if folder is None:
                    raise NotFoundError("Pasta não encontrada.")
                notebook.folder_id = folder_id

        if tag_ids is not None:
            tags = []
            for tag_id in tag_ids:
                tag = await self._tags.get_owned(tag_id, user_id)
                if tag is None:
                    raise NotFoundError(f"Tag {tag_id} não encontrada.")
                tags.append(tag)
            notebook.tags = tags

        if name is not None:
            notebook.name = name
        if description is not None:
            notebook.description = description
        if is_favorite is not None:
            notebook.is_favorite = is_favorite

        async with UnitOfWork(self._session):
            await self._session.flush()

        return await self._notebooks.get_with_relations(notebook.id)

    async def delete_notebook(self, notebook_id: uuid.UUID, user_id: uuid.UUID) -> None:
        notebook = await self.get_notebook(notebook_id, user_id)
        async with UnitOfWork(self._session):
            await self._session.delete(notebook)
            await self._session.flush()

    # ==================================================================== #
    # ESCRITA — Questões no Caderno
    # ==================================================================== #

    async def add_question_to_notebook(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
        note: str | None = None,
    ) -> NotebookQuestion:
        notebook = await self.get_notebook(notebook_id, user_id)

        # Verificar se a questão existe
        question = await self._questions.get_by_id(question_id)
        if question is None:
            raise NotFoundError("Questão não encontrada.")

        # Verificar se a questão já está no caderno
        existing = await self._notebooks.get_question(notebook_id, question_id)
        if existing:
            raise ConflictError("Esta questão já está no caderno.")

        async with UnitOfWork(self._session):
            notebook_question = await self._notebooks.add_question(
                notebook_id=notebook_id,
                question_id=question_id,
                note=note,
            )

        return notebook_question

    async def remove_question_from_notebook(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> None:
        await self.get_notebook(notebook_id, user_id)

        removed = await self._notebooks.remove_question(notebook_id, question_id)
        if not removed:
            raise NotFoundError("Questão não encontrada no caderno.")

    # ==================================================================== #
    # ESCRITA — Pastas
    # ==================================================================== #

    async def create_folder(
        self,
        user_id: uuid.UUID,
        name: str,
        parent_id: uuid.UUID | None = None,
    ) -> NotebookFolder:
        if parent_id is not None:
            parent = await self._folders.get_owned(parent_id, user_id)
            if parent is None:
                raise NotFoundError("Pasta pai não encontrada.")

        folder = NotebookFolder(
            user_id=user_id,
            name=name,
            parent_id=parent_id,
        )

        async with UnitOfWork(self._session):
            await self._folders.add(folder)

        return folder

    async def update_folder(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
    ) -> NotebookFolder:
        folder = await self._folders.get_owned(folder_id, user_id)
        if folder is None:
            raise NotFoundError("Pasta não encontrada.")

        folder.name = name

        async with UnitOfWork(self._session):
            await self._session.flush()

        return folder

    async def delete_folder(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
        move_notebooks_to_parent: bool = True,
    ) -> None:
        folder = await self._folders.get_owned(folder_id, user_id)
        if folder is None:
            raise NotFoundError("Pasta não encontrada.")

        async with UnitOfWork(self._session):
            if move_notebooks_to_parent:
                # Move notebooks para a pasta pai
                parent_id = folder.parent_id
                await self._session.execute(
                    Notebook.__table__.update()
                    .where(Notebook.folder_id == folder_id)
                    .values(folder_id=parent_id)
                )
            await self._session.delete(folder)
            await self._session.flush()

    # ==================================================================== #
    # ESCRITA — Tags
    # ==================================================================== #

    async def create_tag(
        self,
        user_id: uuid.UUID,
        name: str,
    ) -> NotebookTag:
        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")

        existing = await self._tags.get_by_slug(user_id, slug)
        if existing:
            raise ConflictError(f"Tag com slug '{slug}' já existe.")

        tag = NotebookTag(
            user_id=user_id,
            name=name,
            slug=slug,
        )

        async with UnitOfWork(self._session):
            await self._tags.add(tag)

        return tag

    async def delete_tag(self, tag_id: uuid.UUID, user_id: uuid.UUID) -> None:
        tag = await self._tags.get_owned(tag_id, user_id)
        if tag is None:
            raise NotFoundError("Tag não encontrada.")

        async with UnitOfWork(self._session):
            await self._session.delete(tag)
            await self._session.flush()