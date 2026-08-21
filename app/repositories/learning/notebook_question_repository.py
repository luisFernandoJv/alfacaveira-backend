# app/repositories/learning/notebook_question_repository.py
"""Repositório de acesso a dados de `NotebookQuestion`."""

import uuid
from typing import Optional

from sqlalchemy import select, func, delete, or_
from sqlalchemy.orm import selectinload

from app.models.content.question import Question
from app.models.learning.notebook_question import NotebookQuestion
from app.repositories.base import BaseRepository

# 🔥 CORREÇÃO: eager-load da árvore completa de `Question`, não só o objeto
# raso. `QuestionListItem` (usado por `NotebookQuestionResponse.question`)
# exige discipline/subject/topic/exam_board/exam_edition/organization/tags;
# sem carregar cada um deles, o Pydantic tenta lazy-load fora do contexto
# assíncrono da sessão ao serializar e estoura `MissingGreenlet`.
# Mesmo conjunto de relações usado por `QuestionRepository._RELATIONS`
# (app/repositories/content/question_repository.py) — mantido em espelho
# aqui porque `NotebookQuestion.question` é carregado a partir de outra
# raiz de query (NotebookQuestion, não Question), então não dá para
# reaproveitar a tupla de lá diretamente.
_QUESTION_RELATIONS = (
    selectinload(NotebookQuestion.question).selectinload(Question.discipline),
    selectinload(NotebookQuestion.question).selectinload(Question.subject),
    selectinload(NotebookQuestion.question).selectinload(Question.topic),
    selectinload(NotebookQuestion.question).selectinload(Question.exam_board),
    selectinload(NotebookQuestion.question).selectinload(Question.exam_edition),
    selectinload(NotebookQuestion.question).selectinload(Question.organization),
    selectinload(NotebookQuestion.question).selectinload(Question.tags),
    selectinload(NotebookQuestion.question).selectinload(Question.attachments),
)

# Mantido por compatibilidade com quem já importava `_RELATIONS` deste módulo.
_RELATIONS = _QUESTION_RELATIONS


class NotebookQuestionRepository(BaseRepository[NotebookQuestion]):
    """Repositório de questões em cadernos."""

    model = NotebookQuestion

    async def get_owned(
        self,
        notebook_id: uuid.UUID,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> NotebookQuestion | None:
        """Busca uma relação notebook-question validando ownership do notebook."""
        stmt = (
            select(NotebookQuestion)
            .join(NotebookQuestion.notebook)
            .where(
                NotebookQuestion.notebook_id == notebook_id,
                NotebookQuestion.question_id == question_id,
                NotebookQuestion.notebook.has(user_id=user_id),
            )
            .options(*_QUESTION_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_notebook(
        self,
        notebook_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int,
        cursor_id: Optional[uuid.UUID] = None,
        search: Optional[str] = None,
    ) -> tuple[list[NotebookQuestion], int]:
        """Lista questões de um caderno."""
        stmt = (
            select(NotebookQuestion)
            .join(NotebookQuestion.notebook)
            .where(
                NotebookQuestion.notebook_id == notebook_id,
                NotebookQuestion.notebook.has(user_id=user_id),
            )
            .options(*_QUESTION_RELATIONS)
            .order_by(NotebookQuestion.added_at.desc(), NotebookQuestion.id.desc())
            .limit(limit)
        )

        if search:
            search_term = f"%{search}%"
            # 🔥 CORREÇÃO: `statement` não existia neste escopo (NameError
            # silencioso — só estourava quando alguém de fato usava ?search=).
            # O correto é filtrar pela coluna `Question.statement`.
            stmt = stmt.where(
                or_(
                    NotebookQuestion.question.has(Question.statement.ilike(search_term)),
                )
            )

        if cursor_id is not None:
            cursor = await self.get_by_id(cursor_id)
            if cursor is not None:
                stmt = stmt.where(
                    (NotebookQuestion.added_at < cursor.added_at)
                    | (
                        (NotebookQuestion.added_at == cursor.added_at)
                        & (NotebookQuestion.id < cursor.id)
                    )
                )

        result = await self.session.execute(stmt)
        items = list(result.scalars().unique().all())

        # Contagem total
        count_stmt = (
            select(func.count())
            .select_from(NotebookQuestion)
            .join(NotebookQuestion.notebook)
            .where(
                NotebookQuestion.notebook_id == notebook_id,
                NotebookQuestion.notebook.has(user_id=user_id),
            )
        )

        if search:
            search_term = f"%{search}%"
            count_stmt = count_stmt.where(
                NotebookQuestion.question.has(Question.statement.ilike(search_term)),
            )

        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        return items, total

    async def exists(
        self,
        notebook_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> bool:
        """Verifica se uma questão já está no caderno."""
        stmt = select(func.count()).select_from(NotebookQuestion).where(
            NotebookQuestion.notebook_id == notebook_id,
            NotebookQuestion.question_id == question_id,
        )
        result = await self.session.execute(stmt)
        return (result.scalar() or 0) > 0

    async def list_by_ids_with_relations(
        self,
        notebook_question_ids: list[uuid.UUID],
    ) -> list[NotebookQuestion]:
        """Busca por lote de IDs de `NotebookQuestion`, com `question` e sua
        árvore de relações já carregadas.

        Usado para recarregar itens recém-criados (bulk_create) sem cair no
        mesmo bug de lazy-load fora de contexto assíncrono que afetava
        `bulk_create` antes desta correção.
        """
        if not notebook_question_ids:
            return []
        stmt = (
            select(NotebookQuestion)
            .where(NotebookQuestion.id.in_(notebook_question_ids))
            .options(*_QUESTION_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def bulk_create(
        self,
        notebook_id: uuid.UUID,
        question_ids: list[uuid.UUID],
    ) -> list[NotebookQuestion]:
        """Cria múltiplas relações em lote."""
        items = []
        for question_id in question_ids:
            nq = NotebookQuestion(
                notebook_id=notebook_id,
                question_id=question_id,
            )
            self.session.add(nq)
            items.append(nq)

        await self.session.flush()

        # 🔥 CORREÇÃO: recarregar em uma única query com as relações de
        # `question` já carregadas (`self.get_by_id`, herdado de
        # `BaseRepository`, não aplica nenhum `selectinload` — o retorno
        # anterior quebrava na serialização com `MissingGreenlet`).
        ids = [item.id for item in items]
        return await self.list_by_ids_with_relations(ids)

    async def delete_by_notebook_and_question(
        self,
        notebook_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> bool:
        """Remove uma questão de um caderno."""
        stmt = delete(NotebookQuestion).where(
            NotebookQuestion.notebook_id == notebook_id,
            NotebookQuestion.question_id == question_id,
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def delete_by_notebook(
        self,
        notebook_id: uuid.UUID,
    ) -> int:
        """Remove todas as questões de um caderno."""
        stmt = delete(NotebookQuestion).where(
            NotebookQuestion.notebook_id == notebook_id
        )
        result = await self.session.execute(stmt)
        return result.rowcount