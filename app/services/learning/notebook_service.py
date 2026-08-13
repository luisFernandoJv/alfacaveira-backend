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
from app.services.billing.feature_gate_service import FeatureGateService
from app.models.enums import FeatureKey


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
        # `NotebookResponse.question_count` cai no fallback `_question_count`
        # quando `questions` não está carregado (list_by_user não traz essa
        # relação, de propósito, para não pagar N+1 numa listagem).
        for notebook in notebooks:
            notebook._question_count = await self._notebooks.count_questions(notebook.id)
        return notebooks, total

    async def get_notebook(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Notebook:
        """Busca um caderno específico, com as questões carregadas.

        🔥 CORREÇÃO: usa `get_with_questions` (não `get_owned`). O endpoint
        `GET /notebooks/{id}` serializa para `NotebookDetailResponse`, que
        exige `questions: list[QuestionListItem]`. Com `get_owned`, essa
        relação não vinha carregada e o Pydantic tentava lazy-load fora do
        contexto assíncrono da sessão ao montar a resposta — mesma classe de
        erro (`MissingGreenlet`) que quebrava `POST /{id}/questions`.
        """
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

        # 🔥 CORREÇÃO: `notebook` aqui é a instância criada em memória, sem
        # `folder`/`tags` carregados via `selectinload` (só o objeto puro
        # que foi passado pro `session.add()`). `NotebookResponse.folder` é
        # um campo declarado no schema, e o Pydantic acessa esse atributo
        # ao montar a resposta — mesma classe de bug `MissingGreenlet` já
        # documentada em `get_notebook`/`add_question`/`move_questions`
        # (relação não carregada + lazy-load fora do contexto assíncrono).
        # `get_owned` já usa `_RELATIONS` (`selectinload(Notebook.folder)`,
        # `selectinload(Notebook.tags)`), então reaproveitamos o mesmo
        # caminho em vez de duplicar eager-loading aqui.
        notebook = await self._notebooks.get_owned(notebook.id, user_id)

        # Caderno novo: sem questões ainda.
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
        """Lista questões de um caderno."""
        notebook = await self._notebooks.get_owned(notebook_id, user_id)
        if not notebook:
            raise NotFoundError("Caderno não encontrado.")

        return await self._questions.list_by_notebook(
            notebook_id=notebook_id,
            user_id=user_id,
            limit=limit,
            cursor_id=cursor_id,
            search=search,
        )

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

        # 🔥 Recarrega com `question` (e sua árvore de relações) já
        # carregados — ver correção em `notebook_question_repository.py`.
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

        # 🔥 CORREÇÃO: mesma classe de bug do `remove_question` — faltava
        # `UnitOfWork` aqui. `bulk_create()` só faz `session.add()` +
        # `flush()` no repositório (necessário para popular os `id`s antes
        # do SELECT de recarga), mas nunca comita. Sem o commit explícito,
        # a API respondia 201 com as questões "adicionadas", porém eram
        # descartadas ao fechar a sessão no fim da requisição — mesmo
        # sintoma do bug de `remove_question`, só que na direção oposta
        # (perdia adição em vez de perder remoção).
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

        # 🔥 CORREÇÃO: faltava envolver a exclusão em UnitOfWork. `get_db()`
        # (app/database/session.py) só dá rollback em caso de exceção — quem
        # comita é exclusivamente `UnitOfWork.__aexit__`. Sem isso, o DELETE
        # executava e retornava sucesso (204) para o frontend, mas era
        # descartado ao fechar a sessão no fim da requisição: a questão
        # "voltava" a aparecer no próximo GET porque nunca saiu do banco de
        # fato. Todo outro método de escrita deste service já usava
        # UnitOfWork — este era o único que ficou de fora.
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
                    # 🔥 CORREÇÃO: antes chamava `self._session.add(nq)`
                    # diretamente, contornando o repositório. Além de quebrar
                    # o `id` do objeto (só é atribuído no `flush`, e o
                    # `moved_ids.append(nq.id)` seguinte lia `None`), isso
                    # também violava a regra de não duplicar responsabilidade
                    # do repositório (prompt master, item 8/59). Usar
                    # `self._questions.add(...)` garante `id` populado e é o
                    # mesmo caminho já testável via fakes.
                    await self._questions.add(nq)
                    moved_ids.append(nq.id)

        # 🔥 CORREÇÃO: os objetos `NotebookQuestion` criados em memória acima
        # não têm `.question` carregado (nunca foram consultados via SELECT
        # com `selectinload`). Retorná-los direto para o endpoint estourava
        # `MissingGreenlet` na serialização, igual ao bug de `add_question`.
        # Recarregamos em uma única query, já com a árvore de relações.
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

        # 🔥 CORREÇÃO: o filtro de duplicatas antes só rodava dentro do
        # `if quota_limit is not None`. Com quota ilimitada (o caso comum),
        # copiar uma questão que já existe no caderno de destino ia direto
        # pro `bulk_create` e estourava a UNIQUE(notebook_id, question_id)
        # do banco como IntegrityError não tratada (500), em vez de ser
        # simplesmente ignorada — que é o comportamento esperado ao copiar
        # (a seção 21/29 do escopo original já previa isso).
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

        # 🔥 CORREÇÃO: faltava UnitOfWork — mesma classe de bug de
        # `remove_question`/`add_questions_bulk`. Sem isso a cópia
        # "funcionava" na resposta HTTP mas era descartada ao fechar a
        # sessão no fim da requisição.
        async with UnitOfWork(self._session):
            result = await self._questions.bulk_create(target_notebook_id, to_add)
        return result