# app/services/learning/notebook_service.py
"""Regras de negócio de cadernos."""

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ForbiddenError
from app.database.uow import UnitOfWork
from app.models.learning.notebook import Notebook
from app.models.learning.notebook_folder import NotebookFolder
from app.models.learning.notebook_question import NotebookQuestion
from app.models.learning.notebook_tag import NotebookTag
from app.repositories.content.question_repository import QuestionRepository
from app.repositories.learning.notebook_folder_repository import NotebookFolderRepository
from app.repositories.learning.notebook_question_repository import NotebookQuestionRepository
from app.repositories.learning.notebook_repository import NotebookRepository
from app.repositories.learning.notebook_tag_repository import NotebookTagRepository
from app.repositories.practice.question_attempt_repository import QuestionAttemptRepository
from app.repositories.practice.user_question_state_repository import (
    UserQuestionStateRepository,
)
from app.services.billing.feature_gate_service import FeatureGateService
from app.models.enums import FeatureKey, QuestionAnswerStatus


class NotebookService:
    """Serviço de cadernos."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._notebooks = NotebookRepository(session)
        self._questions = NotebookQuestionRepository(session)
        self._folders = NotebookFolderRepository(session)
        self._tags = NotebookTagRepository(session)
        self._question_repo = QuestionRepository(session)
        self._feature_gate = FeatureGateService(session)
        # 🔥 CORREÇÃO (caderno não mostra questão como resolvida): faltavam
        # aqui — sem eles, `question.answer_status`/`question.is_favorite`
        # nunca eram calculados para as questões de um caderno, e o schema
        # (`QuestionListItem`) caía sempre no default `NAO_RESPONDIDA`/
        # `False`, mesmo para questões já respondidas pelo aluno.
        self._states = UserQuestionStateRepository(session)
        self._attempts = QuestionAttemptRepository(session)

    # ==================================================================== #
    # FOLDERS
    # ==================================================================== #

    async def list_folders(self, user_id: uuid.UUID) -> list[NotebookFolder]:
        """Lista todas as pastas do usuário."""
        return await self._folders.list_by_user(user_id)

    async def create_folder(
        self,
        user_id: uuid.UUID,
        name: str,
        parent_id: Optional[uuid.UUID] = None,
    ) -> NotebookFolder:
        """Cria uma nova pasta."""
        existing = await self._folders.get_by_name(user_id, name)
        if existing:
            raise ConflictError(f"Você já possui uma pasta com o nome '{name}'.")

        if parent_id:
            parent = await self._folders.get_owned(parent_id, user_id)
            if not parent:
                raise NotFoundError("Pasta pai não encontrada.")

        folder = NotebookFolder(
            user_id=user_id,
            name=name.strip(),
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
        """Renomeia uma pasta."""
        folder = await self._folders.get_owned(folder_id, user_id)
        if not folder:
            raise NotFoundError("Pasta não encontrada.")

        existing = await self._folders.get_by_name(user_id, name.strip())
        if existing and existing.id != folder_id:
            raise ConflictError(f"Você já possui uma pasta com o nome '{name}'.")

        folder.name = name.strip()

        async with UnitOfWork(self._session):
            await self._session.flush()

        return folder

    async def delete_folder(self, folder_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Exclui uma pasta (move cadernos para root)."""
        folder = await self._folders.get_owned(folder_id, user_id)
        if not folder:
            raise NotFoundError("Pasta não encontrada.")

        # Mover cadernos para root
        notebooks, _ = await self._notebooks.list_by_user(
            user_id, limit=1000, folder_id=folder_id
        )
        for notebook in notebooks:
            notebook.folder_id = None

        async with UnitOfWork(self._session):
            await self._session.flush()
            await self._folders.delete_cascade(folder_id)

    # ==================================================================== #
    # TAGS
    # ==================================================================== #

    async def list_tags(self) -> list[NotebookTag]:
        """Lista todas as tags disponíveis."""
        return await self._tags.list_all()

    async def create_tag(self, name: str) -> NotebookTag:
        """Cria uma nova tag."""
        existing = await self._tags.get_by_name(name.strip())
        if existing:
            return existing

        import re
        slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")

        tag = NotebookTag(name=name.strip(), slug=slug)

        async with UnitOfWork(self._session):
            await self._tags.add(tag)

        return tag

    # ==================================================================== #
    # NOTEBOOKS
    # ==================================================================== #

    async def list_notebooks(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
        cursor_id: Optional[uuid.UUID] = None,
        folder_id: Optional[uuid.UUID] = None,
        favorite: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Notebook], int]:
        """Lista cadernos do usuário."""
        notebooks, total = await self._notebooks.list_by_user(
            user_id=user_id,
            limit=limit,
            cursor_id=cursor_id,
            folder_id=folder_id,
            favorite=favorite,
            search=search,
        )
        for notebook in notebooks:
            notebook._question_count = await self._notebooks.count_questions(notebook.id)
        return notebooks, total

    async def get_notebook(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Notebook:
        """Busca um caderno específico, com as questões carregadas."""
        notebook = await self._notebooks.get_with_questions(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        notebook._question_count = len(notebook.questions)
        return notebook

    async def create_notebook(
        self,
        user_id: uuid.UUID,
        name: str,
        description: Optional[str] = None,
        folder_id: Optional[uuid.UUID] = None,
        tag_ids: Optional[list[uuid.UUID]] = None,
    ) -> Notebook:
        """Cria um novo caderno."""
        # Verificar feature gate
        has_feature = await self._feature_gate.has_feature(user_id, FeatureKey.NOTEBOOKS)
        if not has_feature:
            raise ForbiddenError(
                "Seu plano atual não inclui a criação de cadernos. "
                "Faça upgrade para o plano Standard ou Pro."
            )

        existing = await self._notebooks.get_by_name(user_id, name.strip())
        if existing:
            raise ConflictError(f"Você já possui um caderno com o nome '{name}'.")

        if folder_id:
            folder = await self._folders.get_owned(folder_id, user_id)
            if not folder:
                raise NotFoundError("Pasta não encontrada.")

        tags = []
        if tag_ids:
            tags = await self._tags.list_by_ids(tag_ids)
            if len(tags) != len(tag_ids):
                raise NotFoundError("Uma ou mais tags não foram encontradas.")

        notebook = Notebook(
            user_id=user_id,
            name=name.strip(),
            description=description.strip() if description else None,
            folder_id=folder_id,
        )
        notebook.tags = tags

        async with UnitOfWork(self._session):
            await self._notebooks.add(notebook)

        # 🔥 CRÍTICO: Refresh do objeto e recarregar relações para evitar
        # MissingGreenlet quando o router acessar notebook.folder/tags.
        await self._session.refresh(notebook)

        if notebook.folder_id:
            folder = await self._folders.get_owned(notebook.folder_id, user_id)
            notebook.folder = folder

        if tag_ids:
            tags = await self._tags.list_by_ids(tag_ids)
            notebook.tags = tags

        notebook._question_count = 0
        return notebook

    async def update_notebook(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        folder_id: Optional[uuid.UUID] = None,
        is_favorite: Optional[bool] = None,
        tag_ids: Optional[list[uuid.UUID]] = None,
    ) -> Notebook:
        """Atualiza um caderno."""
        # Buscar com relações já carregadas
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        if name is not None and name.strip() != notebook.name:
            existing = await self._notebooks.get_by_name(user_id, name.strip())
            if existing and existing.id != notebook_id:
                raise ConflictError(f"Você já possui um caderno com o nome '{name}'.")
            notebook.name = name.strip()

        if description is not None:
            notebook.description = description.strip() if description else None

        if folder_id is not None:
            if folder_id:
                folder = await self._folders.get_owned(folder_id, user_id)
                if not folder:
                    raise NotFoundError("Pasta não encontrada.")
            notebook.folder_id = folder_id

        if is_favorite is not None:
            notebook.is_favorite = is_favorite

        if tag_ids is not None:
            tags = await self._tags.list_by_ids(tag_ids)
            if len(tags) != len(tag_ids):
                raise NotFoundError("Uma ou mais tags não foram encontradas.")
            notebook.tags = tags

        async with UnitOfWork(self._session):
            await self._session.flush()

            # 🔥 CRÍTICO: Refresh do objeto para recarregar todas as colunas
            # do banco, incluindo updated_at que é atualizado pelo trigger
            await self._session.refresh(notebook)

            # Recarregar relações explicitamente
            if notebook.folder_id:
                folder = await self._folders.get_owned(notebook.folder_id, user_id)
                notebook.folder = folder

            # Recarregar tags
            if tag_ids is not None:
                tags = await self._tags.list_by_ids(tag_ids)
                notebook.tags = tags

        notebook._question_count = await self._notebooks.count_questions(notebook_id)
        return notebook

    async def delete_notebook(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Exclui um caderno (cascade exclui relações)."""
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        async with UnitOfWork(self._session):
            await self._notebooks.delete(notebook_id)
            await self._session.flush()

    # ==================================================================== #
    # QUESTIONS IN NOTEBOOK
    # ==================================================================== #

    async def list_notebook_questions(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int = 20,
        cursor_id: Optional[uuid.UUID] = None,
        search: Optional[str] = None,
    ) -> tuple[list[NotebookQuestion], int]:
        """Lista questões de um caderno.

        🔥 CORREÇÃO (caderno "esquece" questão respondida): esta listagem
        devolve `NotebookQuestion.question` (um `Question` do banco), que o
        schema `QuestionListItem` serializa incluindo `is_favorite` e
        `answer_status` — mas esses dois são atributos TRANSIENTES (não
        colunas), que precisam ser calculados e atribuídos explicitamente em
        cada request, exatamente como `QuestionService.list_questions` já
        fazia para o Banco de Questões. Sem isso, todo item de caderno caía
        no default do schema (`NAO_RESPONDIDA` / `False`), então uma questão
        recém-respondida no treino continuava aparecendo como "não feita" ao
        montar/abrir um caderno — mesmo com o `QuestionAttempt` já salvo.
        """
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        items, total = await self._questions.list_by_notebook(
            notebook_id=notebook_id,
            user_id=user_id,
            limit=limit,
            cursor_id=cursor_id,
            search=search,
        )
        await self._attach_answer_state(items, user_id)
        return items, total

    async def _attach_answer_state(
        self, items: list[NotebookQuestion], user_id: uuid.UUID
    ) -> None:
        """Preenche `item.question.is_favorite`/`answer_status` em lote —
        mesma lógica de `QuestionService.list_questions` (duas queries
        agregadas, independente da quantidade de itens do caderno).
        """
        if not items:
            return
        question_ids = [item.question_id for item in items]
        favorited_ids, correct_map = await self._session_gather(
            self._states.get_favorited_ids(user_id, question_ids),
            self._attempts.get_correct_status_map(user_id, question_ids),
        )
        for item in items:
            item.question.is_favorite = item.question_id in favorited_ids
            if item.question_id not in correct_map:
                item.question.answer_status = QuestionAnswerStatus.NAO_RESPONDIDA
            elif correct_map[item.question_id]:
                item.question.answer_status = QuestionAnswerStatus.ACERTOU
            else:
                item.question.answer_status = QuestionAnswerStatus.ERROU

    @staticmethod
    async def _session_gather(*coros):
        """Executa as queries de estado em sequência (mesma razão de
        `QuestionService._session_gather`): as coroutines compartilham a
        MESMA `AsyncSession`, que não é concorrente — `asyncio.gather` aqui
        corromperia o estado da sessão.
        """
        results = []
        for coro in coros:
            results.append(await coro)
        return results


    async def list_export_questions(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        question_ids: list[uuid.UUID] | None = None,
    ) -> tuple[Notebook, list[NotebookQuestion]]:
        """Valida posse e carrega as questões completas para exportação."""
        notebook = await self.get_notebook(notebook_id, user_id)
        items = await self._questions.list_for_export(
            notebook_id=notebook_id,
            user_id=user_id,
            question_ids=question_ids,
        )
        return notebook, items

    async def add_question(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> NotebookQuestion:
        """Adiciona uma questão ao caderno."""
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        question = await self._question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundError("Questão não encontrada.")

        if await self._questions.exists(notebook_id, question_id):
            raise ConflictError("Esta questão já está no caderno.")

        current_count = await self._notebooks.count_questions(notebook_id)
        quota_limit = await self._feature_gate.get_quota_limit(
            user_id, FeatureKey.NOTEBOOK_MAX_QUESTIONS
        )
        if quota_limit is not None and current_count >= quota_limit:
            raise ForbiddenError(
                f"Limite de {quota_limit} questões por caderno foi atingido."
            )

        notebook_question = NotebookQuestion(
            notebook_id=notebook_id,
            question_id=question_id,
        )

        async with UnitOfWork(self._session):
            await self._questions.add(notebook_question)

        return await self._questions.get_owned(notebook_id, question_id, user_id)

    async def add_questions_bulk(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        question_ids: list[uuid.UUID],
    ) -> list[NotebookQuestion]:
        """Adiciona múltiplas questões ao caderno."""
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        current_count = await self._notebooks.count_questions(notebook_id)
        quota_limit = await self._feature_gate.get_quota_limit(
            user_id, FeatureKey.NOTEBOOK_MAX_QUESTIONS
        )
        if quota_limit is not None and current_count + len(question_ids) > quota_limit:
            raise ForbiddenError(
                f"Limite de {quota_limit} questões por caderno seria excedido."
            )

        # Remover duplicatas
        to_add = []
        for qid in question_ids:
            if not await self._questions.exists(notebook_id, qid):
                to_add.append(qid)

        if not to_add:
            return []

        # Verificar se todas as questões existem
        questions = await self._question_repo.list_by_ids(to_add)
        if len(questions) != len(to_add):
            raise NotFoundError("Uma ou mais questões não foram encontradas.")

        async with UnitOfWork(self._session):
            result = await self._questions.bulk_create(notebook_id, to_add)
        return result

    async def remove_question(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> None:
        """Remove uma questão do caderno."""
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        async with UnitOfWork(self._session):
            removed = await self._questions.delete_by_notebook_and_question(
                notebook_id, question_id
            )
            if not removed:
                raise NotFoundError("Questão não encontrada neste caderno.")

    async def move_questions(
        self,
        source_notebook_id: uuid.UUID,
        target_notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        question_ids: list[uuid.UUID],
    ) -> list[NotebookQuestion]:
        """Move questões para outro caderno."""
        if source_notebook_id == target_notebook_id:
            raise ConflictError("Os cadernos de origem e destino são os mesmos.")

        source = await self._notebooks.get_owned(source_notebook_id, user_id)
        if not source:
            raise NotFoundError("Caderno de origem não encontrado.")

        target = await self._notebooks.get_owned(target_notebook_id, user_id)
        if not target:
            raise NotFoundError("Caderno de destino não encontrado.")

        current_count = await self._notebooks.count_questions(target_notebook_id)
        quota_limit = await self._feature_gate.get_quota_limit(
            user_id, FeatureKey.NOTEBOOK_MAX_QUESTIONS
        )
        if quota_limit is not None and current_count + len(question_ids) > quota_limit:
            raise ForbiddenError(
                f"Limite de {quota_limit} questões no caderno destino seria excedido."
            )

        moved_ids: list[uuid.UUID] = []
        async with UnitOfWork(self._session):
            for qid in question_ids:
                if not await self._questions.exists(source_notebook_id, qid):
                    continue

                await self._questions.delete_by_notebook_and_question(
                    source_notebook_id, qid
                )

                if not await self._questions.exists(target_notebook_id, qid):
                    nq = NotebookQuestion(
                        notebook_id=target_notebook_id,
                        question_id=qid,
                    )
                    await self._questions.add(nq)
                    moved_ids.append(nq.id)

        return await self._questions.list_by_ids_with_relations(moved_ids)

    async def copy_questions(
        self,
        source_notebook_id: uuid.UUID,
        target_notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        question_ids: list[uuid.UUID],
    ) -> list[NotebookQuestion]:
        """Copia questões para outro caderno."""
        if source_notebook_id == target_notebook_id:
            raise ConflictError("Os cadernos de origem e destino são os mesmos.")

        source = await self._notebooks.get_owned(source_notebook_id, user_id)
        if not source:
            raise NotFoundError("Caderno de origem não encontrado.")

        target = await self._notebooks.get_owned(target_notebook_id, user_id)
        if not target:
            raise NotFoundError("Caderno de destino não encontrado.")

        current_count = await self._notebooks.count_questions(target_notebook_id)
        quota_limit = await self._feature_gate.get_quota_limit(
            user_id, FeatureKey.NOTEBOOK_MAX_QUESTIONS
        )

        # Remover duplicatas
        to_add = []
        for qid in question_ids:
            if not await self._questions.exists(target_notebook_id, qid):
                to_add.append(qid)

        if not to_add:
            return []

        if quota_limit is not None and current_count + len(to_add) > quota_limit:
            raise ForbiddenError(
                f"Limite de {quota_limit} questões no caderno destino seria excedido."
            )

        async with UnitOfWork(self._session):
            result = await self._questions.bulk_create(target_notebook_id, to_add)
        return result