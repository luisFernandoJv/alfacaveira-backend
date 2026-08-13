# tests/unit/learning/fakes.py
"""Fakes para testes de cadernos."""

import uuid
from typing import Optional, List
from datetime import datetime

from app.models.learning.notebook import Notebook
from app.models.learning.notebook_folder import NotebookFolder
from app.models.learning.notebook_question import NotebookQuestion
from app.models.learning.notebook_tag import NotebookTag


class FakeNotebookRepository:
    """Fake para NotebookRepository."""

    def __init__(self):
        self.store: dict[uuid.UUID, Notebook] = {}

    def seed(self, *notebooks: Notebook):
        for n in notebooks:
            self.store[n.id] = n

    async def get_owned(self, notebook_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Notebook]:
        n = self.store.get(notebook_id)
        if n and n.user_id == user_id:
            return n
        return None

    async def get_with_questions(self, notebook_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Notebook]:
        """Espelha `get_owned`: os testes unitários não usam SQLAlchemy real,
        então não há lazy-load a simular. `notebook.questions` já é uma lista
        vazia por padrão em objetos transientes (não persistidos), então
        nenhum carregamento extra é necessário aqui."""
        return await self.get_owned(notebook_id, user_id)

    async def get_by_id(self, notebook_id: uuid.UUID) -> Optional[Notebook]:
        return self.store.get(notebook_id)

    async def get_by_name(self, user_id: uuid.UUID, name: str) -> Optional[Notebook]:
        for n in self.store.values():
            if n.user_id == user_id and n.name == name:
                return n
        return None

    async def list_by_user(self, user_id: uuid.UUID, limit: int, **kwargs) -> tuple[List[Notebook], int]:
        items = [n for n in self.store.values() if n.user_id == user_id]
        
        folder_id = kwargs.get("folder_id")
        if folder_id is not None:
            items = [n for n in items if n.folder_id == folder_id]

        favorite = kwargs.get("favorite")
        if favorite is not None:
            items = [n for n in items if n.is_favorite == favorite]

        search = kwargs.get("search")
        if search:
            search_lower = search.lower()
            items = [
                n for n in items
                if search_lower in n.name.lower() or (n.description and search_lower in n.description.lower())
            ]

        return items[:limit], len(items)

    async def count_questions(self, notebook_id: uuid.UUID) -> int:
        count = 0
        for n in self.store.values():
            if n.id == notebook_id:
                count = len(n.questions) if hasattr(n, 'questions') else 0
                break
        return count

    async def add(self, notebook: Notebook) -> Notebook:
        if not notebook.id:
            notebook.id = uuid.uuid4()
        if notebook.is_favorite is None:
            notebook.is_favorite = False
        self.store[notebook.id] = notebook
        return notebook

    async def toggle_favorite(self, notebook_id: uuid.UUID, user_id: uuid.UUID, is_favorite: bool) -> Optional[Notebook]:
        n = await self.get_owned(notebook_id, user_id)
        if n:
            n.is_favorite = is_favorite
        return n

    async def delete(self, notebook_id: uuid.UUID) -> bool:
        """Remove um caderno do store."""
        if notebook_id in self.store:
            del self.store[notebook_id]
            return True
        return False


class FakeNotebookQuestionRepository:
    """Fake para NotebookQuestionRepository."""

    def __init__(self):
        self.store: dict[uuid.UUID, NotebookQuestion] = {}

    def seed(self, *questions: NotebookQuestion):
        for q in questions:
            self.store[q.id] = q

    async def get_owned(self, notebook_id: uuid.UUID, question_id: uuid.UUID, user_id: uuid.UUID) -> Optional[NotebookQuestion]:
        for q in self.store.values():
            if q.notebook_id == notebook_id and q.question_id == question_id:
                return q
        return None

    async def exists(self, notebook_id: uuid.UUID, question_id: uuid.UUID) -> bool:
        for q in self.store.values():
            if q.notebook_id == notebook_id and q.question_id == question_id:
                return True
        return False

    async def add(self, nq: NotebookQuestion) -> NotebookQuestion:
        if not nq.id:
            nq.id = uuid.uuid4()
        self.store[nq.id] = nq
        return nq

    async def list_by_ids_with_relations(self, notebook_question_ids: list[uuid.UUID]) -> List[NotebookQuestion]:
        """Espelha o método real (usado por `move_questions` para recarregar
        os itens movidos). Sem SQLAlchemy real, não há relação para
        eager-load — apenas retorna os itens já no store."""
        return [self.store[i] for i in notebook_question_ids if i in self.store]

    async def bulk_create(self, notebook_id: uuid.UUID, question_ids: list[uuid.UUID]) -> list[NotebookQuestion]:
        items = []
        for qid in question_ids:
            nq = NotebookQuestion(
                id=uuid.uuid4(),
                notebook_id=notebook_id,
                question_id=qid,
            )
            self.store[nq.id] = nq
            items.append(nq)
        return items

    async def delete_by_notebook_and_question(self, notebook_id: uuid.UUID, question_id: uuid.UUID) -> bool:
        for key, q in list(self.store.items()):
            if q.notebook_id == notebook_id and q.question_id == question_id:
                del self.store[key]
                return True
        return False

    async def list_by_notebook(self, notebook_id: uuid.UUID, user_id: uuid.UUID, limit: int, **kwargs) -> tuple[List[NotebookQuestion], int]:
        items = [q for q in self.store.values() if q.notebook_id == notebook_id]
        search = kwargs.get("search")
        if search:
            search_lower = search.lower()
            items = [q for q in items if search_lower in str(q.question_id)]
        return items[:limit], len(items)


class FakeNotebookFolderRepository:
    """Fake para NotebookFolderRepository."""

    def __init__(self):
        self.store: dict[uuid.UUID, NotebookFolder] = {}

    def seed(self, *folders: NotebookFolder):
        for f in folders:
            self.store[f.id] = f

    async def get_owned(self, folder_id: uuid.UUID, user_id: uuid.UUID) -> Optional[NotebookFolder]:
        f = self.store.get(folder_id)
        if f and f.user_id == user_id:
            return f
        return None

    async def get_by_name(self, user_id: uuid.UUID, name: str) -> Optional[NotebookFolder]:
        for f in self.store.values():
            if f.user_id == user_id and f.name == name:
                return f
        return None

    async def list_by_user(self, user_id: uuid.UUID) -> List[NotebookFolder]:
        return [f for f in self.store.values() if f.user_id == user_id]

    async def add(self, folder: NotebookFolder) -> NotebookFolder:
        if not folder.id:
            folder.id = uuid.uuid4()
        self.store[folder.id] = folder
        return folder

    async def delete_cascade(self, folder_id: uuid.UUID) -> None:
        to_delete = [folder_id]
        for f in list(self.store.values()):
            if f.parent_id in to_delete:
                to_delete.append(f.id)
        for fid in to_delete:
            self.store.pop(fid, None)


class FakeNotebookTagRepository:
    """Fake para NotebookTagRepository."""

    def __init__(self):
        self.store: dict[uuid.UUID, NotebookTag] = {}

    def seed(self, *tags: NotebookTag):
        for t in tags:
            self.store[t.id] = t

    async def list_all(self) -> List[NotebookTag]:
        return list(self.store.values())

    async def get_by_name(self, name: str) -> Optional[NotebookTag]:
        for t in self.store.values():
            if t.name == name:
                return t
        return None

    async def get_by_slug(self, slug: str) -> Optional[NotebookTag]:
        for t in self.store.values():
            if t.slug == slug:
                return t
        return None

    async def list_by_ids(self, tag_ids: List[uuid.UUID]) -> List[NotebookTag]:
        return [t for t in self.store.values() if t.id in tag_ids]

    async def add(self, tag: NotebookTag) -> NotebookTag:
        if not tag.id:
            tag.id = uuid.uuid4()
        self.store[tag.id] = tag
        return tag