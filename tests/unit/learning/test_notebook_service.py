# tests/unit/learning/test_notebook_service.py
"""Testes unitários do NotebookService."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ForbiddenError
from app.services.learning.notebook_service import NotebookService
from tests.unit.learning.fakes import (
    FakeNotebookRepository,
    FakeNotebookQuestionRepository,
    FakeNotebookFolderRepository,
    FakeNotebookTagRepository,
)


class TestNotebookService:
    """Testes do NotebookService."""

    @pytest.fixture
    def service(self):
        """Cria um service com repositórios fakes."""
        session = AsyncMock()
        service = NotebookService(session)
        service._notebooks = FakeNotebookRepository()
        service._questions = FakeNotebookQuestionRepository()
        service._folders = FakeNotebookFolderRepository()
        service._tags = FakeNotebookTagRepository()
        # Mock do feature gate
        service._feature_gate = AsyncMock()
        service._feature_gate.get_quota_limit.return_value = None  # Ilimitado
        # Mock do question repo
        service._question_repo = AsyncMock()
        service._question_repo.get_by_id = AsyncMock(return_value=True)
        service._question_repo.list_by_ids = AsyncMock(return_value=[])
        return service

    @pytest.fixture
    def user_id(self):
        return uuid.uuid4()

    # ==================================================================== #
    # FOLDERS
    # ==================================================================== #

    async def test_create_folder_success(self, service, user_id):
        """Testa criação de pasta bem-sucedida."""
        folder = await service.create_folder(user_id, "Minha Pasta")
        assert folder.user_id == user_id
        assert folder.name == "Minha Pasta"
        assert folder.parent_id is None

    async def test_create_folder_duplicate_name(self, service, user_id):
        """Testa criação de pasta com nome duplicado."""
        await service.create_folder(user_id, "Minha Pasta")
        with pytest.raises(ConflictError):
            await service.create_folder(user_id, "Minha Pasta")

    async def test_create_folder_with_parent(self, service, user_id):
        """Testa criação de subpasta."""
        parent = await service.create_folder(user_id, "Pai")
        child = await service.create_folder(user_id, "Filho", parent.id)
        assert child.parent_id == parent.id

    async def test_update_folder_success(self, service, user_id):
        """Testa renomear pasta."""
        folder = await service.create_folder(user_id, "Antigo")
        updated = await service.update_folder(folder.id, user_id, "Novo")
        assert updated.name == "Novo"

    async def test_update_folder_not_found(self, service, user_id):
        """Testa renomear pasta inexistente."""
        with pytest.raises(NotFoundError):
            await service.update_folder(uuid.uuid4(), user_id, "Nome")

    async def test_delete_folder_moves_notebooks_to_root(self, service, user_id):
        """Testa excluir pasta move cadernos para root."""
        folder = await service.create_folder(user_id, "Pasta")
        notebook = await service.create_notebook(user_id, "Caderno", folder_id=folder.id)
        assert notebook.folder_id == folder.id

        await service.delete_folder(folder.id, user_id)
        updated = await service.get_notebook(notebook.id, user_id)
        assert updated.folder_id is None

    # ==================================================================== #
    # NOTEBOOKS
    # ==================================================================== #

    async def test_create_notebook_success(self, service, user_id):
        """Testa criação de caderno bem-sucedida."""
        notebook = await service.create_notebook(user_id, "Meu Caderno", "Descrição")
        assert notebook.user_id == user_id
        assert notebook.name == "Meu Caderno"
        assert notebook.description == "Descrição"
        assert notebook.is_favorite is False

    async def test_create_notebook_duplicate_name(self, service, user_id):
        """Testa criação de caderno com nome duplicado."""
        await service.create_notebook(user_id, "Caderno 1")
        with pytest.raises(ConflictError):
            await service.create_notebook(user_id, "Caderno 1")

    async def test_create_notebook_with_folder(self, service, user_id):
        """Testa criação de caderno em pasta."""
        folder = await service.create_folder(user_id, "Pasta")
        notebook = await service.create_notebook(user_id, "Caderno", folder_id=folder.id)
        assert notebook.folder_id == folder.id

    async def test_get_notebook_success(self, service, user_id):
        """Testa buscar caderno."""
        created = await service.create_notebook(user_id, "Meu Caderno")
        fetched = await service.get_notebook(created.id, user_id)
        assert fetched.id == created.id

    async def test_get_notebook_not_found(self, service, user_id):
        """Testa buscar caderno inexistente."""
        with pytest.raises(NotFoundError):
            await service.get_notebook(uuid.uuid4(), user_id)

    async def test_get_notebook_not_owned(self, service, user_id):
        """Testa buscar caderno de outro usuário."""
        other_user = uuid.uuid4()
        notebook = await service.create_notebook(user_id, "Meu Caderno")
        with pytest.raises(NotFoundError):
            await service.get_notebook(notebook.id, other_user)

    async def test_update_notebook_success(self, service, user_id):
        """Testa atualizar caderno."""
        notebook = await service.create_notebook(user_id, "Antigo")
        updated = await service.update_notebook(
            notebook.id, user_id,
            name="Novo",
            description="Nova descrição",
            is_favorite=True,
        )
        assert updated.name == "Novo"
        assert updated.description == "Nova descrição"
        assert updated.is_favorite is True

    async def test_update_notebook_duplicate_name(self, service, user_id):
        """Testa atualizar caderno com nome duplicado."""
        await service.create_notebook(user_id, "Caderno 1")
        notebook2 = await service.create_notebook(user_id, "Caderno 2")
        with pytest.raises(ConflictError):
            await service.update_notebook(notebook2.id, user_id, name="Caderno 1")

    async def test_delete_notebook_success(self, service, user_id):
        """Testa excluir caderno."""
        notebook = await service.create_notebook(user_id, "Meu Caderno")
        await service.delete_notebook(notebook.id, user_id)
        with pytest.raises(NotFoundError):
            await service.get_notebook(notebook.id, user_id)

    # ==================================================================== #
    # QUESTIONS IN NOTEBOOK
    # ==================================================================== #

    async def test_add_question_success(self, service, user_id):
        """Testa adicionar questão ao caderno."""
        notebook = await service.create_notebook(user_id, "Meu Caderno")
        question_id = uuid.uuid4()

        nq = await service.add_question(notebook.id, user_id, question_id)
        assert nq.notebook_id == notebook.id
        assert nq.question_id == question_id

    async def test_add_question_already_exists(self, service, user_id):
        """Testa adicionar questão que já está no caderno."""
        notebook = await service.create_notebook(user_id, "Meu Caderno")
        question_id = uuid.uuid4()

        await service.add_question(notebook.id, user_id, question_id)
        with pytest.raises(ConflictError):
            await service.add_question(notebook.id, user_id, question_id)

    async def test_add_question_quota_exceeded(self, service, user_id):
        """Testa adicionar questão com quota excedida."""
        notebook = await service.create_notebook(user_id, "Meu Caderno")
        question_id = uuid.uuid4()
        service._feature_gate.get_quota_limit.return_value = 0

        with pytest.raises(ForbiddenError):
            await service.add_question(notebook.id, user_id, question_id)

    async def test_remove_question_success(self, service, user_id):
        """Testa remover questão do caderno."""
        notebook = await service.create_notebook(user_id, "Meu Caderno")
        question_id = uuid.uuid4()

        await service.add_question(notebook.id, user_id, question_id)
        await service.remove_question(notebook.id, user_id, question_id)

        with pytest.raises(NotFoundError):
            await service.remove_question(notebook.id, user_id, question_id)

    async def test_move_questions_success(self, service, user_id):
        """Testa mover questões entre cadernos."""
        source = await service.create_notebook(user_id, "Origem")
        target = await service.create_notebook(user_id, "Destino")
        q1 = uuid.uuid4()
        q2 = uuid.uuid4()

        service._question_repo.list_by_ids = AsyncMock(return_value=[True, True])

        await service.add_question(source.id, user_id, q1)
        await service.add_question(source.id, user_id, q2)

        assert source.id != target.id

        result = await service.move_questions(
            source.id, target.id, user_id, [q1, q2]
        )
        assert len(result) == 2

        with pytest.raises(NotFoundError):
            await service.remove_question(source.id, user_id, q1)

    async def test_copy_questions_success(self, service, user_id):
        """Testa copiar questões entre cadernos."""
        source = await service.create_notebook(user_id, "Origem")
        target = await service.create_notebook(user_id, "Destino")
        q1 = uuid.uuid4()

        service._question_repo.list_by_ids = AsyncMock(return_value=[True])

        await service.add_question(source.id, user_id, q1)

        assert source.id != target.id

        result = await service.copy_questions(
            source.id, target.id, user_id, [q1]
        )
        assert len(result) == 1

        await service.remove_question(source.id, user_id, q1)