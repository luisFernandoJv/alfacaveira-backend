"""Repositório de acesso a dados de `Question`.

Listagem pública filtrável + busca full-text, paginação cursor-based (mesmo
padrão de `UserRepository.list_paginated`, Etapa 6) e carregamento antecipado
(`selectinload`) das relações usadas pelos schemas de resposta, para evitar
N+1 nas listagens.

ETAPA 4 (auditoria Banco de Questões, 2026-08-14): `answer_status` (certas/
erradas/não respondidas) migrou de filtro client-side (`hooks/
use-question-filters.ts` no frontend) para filtro real de servidor, via
subquery contra `question_attempts` — mesma semântica já usada em
`QuestionAttemptRepository.get_correct_status_map` (bool_or por questão:
acertou se acertou em QUALQUER tentativa). `favorite` continua client-side
nesta etapa — não migrado junto por depender de estado otimista no
frontend (ver comentário em `use-question-filters.ts`); registrado como
próxima dívida, não implementado aqui para não misturar duas mudanças de
contrato numa unidade só.

ETAPA 5 (2026-08-14): `favorite_only` ("somente favoritos") migrado de
filtro client-side para filtro real de servidor, via subquery contra
`user_question_states` — mesmo padrão de `answer_status` (ETAPA 4). O
estado otimista do clique na estrela (`hooks/use-favorites.ts`) NÃO foi
tocado: a estrela continua respondendo instantaneamente porque reflete
`favoriteIds` local, independente desta query. Só a LISTA filtrada por
"somente favoritos" passou a vir do backend (corrige a limitação anterior
de só filtrar dentro da página já carregada).
"""

import uuid
from dataclasses import dataclass, replace

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.models.content.question import Question
from app.models.enums import QuestionAnswerStatus, QuestionDifficulty, QuestionStatus
from app.models.practice.question_attempt import QuestionAttempt
from app.models.practice.user_question_state import UserQuestionState
from app.repositories.base import BaseRepository

_RELATIONS = (
    selectinload(Question.discipline),
    selectinload(Question.subject),
    selectinload(Question.topic),
    selectinload(Question.exam_board),
    selectinload(Question.exam_edition),
    selectinload(Question.organization),
    selectinload(Question.alternatives),
    selectinload(Question.tags),
)


@dataclass
class QuestionFilters:
    """Filtros da listagem pública, todos opcionais (combinados com AND)."""

    discipline_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    exam_board_id: uuid.UUID | None = None
    exam_edition_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    year: int | None = None
    difficulty: QuestionDifficulty | None = None
    status: QuestionStatus | None = None
    tag_id: uuid.UUID | None = None
    search: str | None = None
    # ETAPA 4: filtro real de servidor por status de resposta do usuário
    # autenticado. Exige `user_id` — sem ele, o filtro é ignorado (ver
    # `_apply_filters`), igual ao comportamento anterior (sem filtro).
    answer_status: QuestionAnswerStatus | None = None
    # ETAPA 5: filtro real de servidor por "somente favoritos" do usuário
    # autenticado. Mesma regra de `answer_status`: exige `user_id`, senão é
    # ignorado.
    favorite_only: bool | None = None
    user_id: uuid.UUID | None = None


class QuestionRepository(BaseRepository[Question]):
    model = Question

    def _apply_filters(
        self, stmt: Select[tuple[Question]], filters: QuestionFilters
    ) -> Select[tuple[Question]]:
        if filters.discipline_id is not None:
            stmt = stmt.where(Question.discipline_id == filters.discipline_id)
        if filters.subject_id is not None:
            stmt = stmt.where(Question.subject_id == filters.subject_id)
        if filters.topic_id is not None:
            stmt = stmt.where(Question.topic_id == filters.topic_id)
        if filters.exam_board_id is not None:
            stmt = stmt.where(Question.exam_board_id == filters.exam_board_id)
        if filters.exam_edition_id is not None:
            stmt = stmt.where(Question.exam_edition_id == filters.exam_edition_id)
        if filters.organization_id is not None:
            stmt = stmt.where(Question.organization_id == filters.organization_id)
        if filters.year is not None:
            stmt = stmt.where(Question.year == filters.year)
        if filters.difficulty is not None:
            stmt = stmt.where(Question.difficulty == filters.difficulty)
        if filters.status is not None:
            stmt = stmt.where(Question.status == filters.status)
        if filters.tag_id is not None:
            stmt = stmt.where(Question.tags.any(id=filters.tag_id))
        if filters.search:
            # `search_vector` é mantido por trigger (to_tsvector('portuguese', ...)),
            # então a query também precisa ser 'portuguese' para casar os lexemas.
            stmt = stmt.where(
                Question.search_vector.op("@@")(func.plainto_tsquery("portuguese", filters.search))
            )
        if filters.answer_status is not None and filters.user_id is not None:
            if filters.answer_status == QuestionAnswerStatus.NAO_RESPONDIDA:
                answered_subq = select(QuestionAttempt.question_id).where(
                    QuestionAttempt.user_id == filters.user_id,
                )
                stmt = stmt.where(Question.id.notin_(answered_subq))
            else:
                # Mesma semântica de `QuestionAttemptRepository.get_correct_status_map`:
                # "acertou" = acertou em QUALQUER tentativa; "errou" = tem
                # tentativa(s), mas nunca acertou.
                correct_target = filters.answer_status == QuestionAnswerStatus.ACERTOU
                status_subq = (
                    select(QuestionAttempt.question_id)
                    .where(QuestionAttempt.user_id == filters.user_id)
                    .group_by(QuestionAttempt.question_id)
                    .having(func.bool_or(QuestionAttempt.is_correct).is_(correct_target))
                )
                stmt = stmt.where(Question.id.in_(status_subq))
        if filters.favorite_only and filters.user_id is not None:
            # Mesmo índice parcial já usado por `UserQuestionStateRepository
            # .list_favorites`/`get_favorited_ids` (`ix_uqs_favorites`,
            # `WHERE is_favorite = true`) — não precisa de índice novo.
            favorite_subq = select(UserQuestionState.question_id).where(
                UserQuestionState.user_id == filters.user_id,
                UserQuestionState.is_favorite.is_(True),
            )
            stmt = stmt.where(Question.id.in_(favorite_subq))
        return stmt

    async def get_with_relations(self, question_id: uuid.UUID) -> Question | None:
        stmt = select(Question).where(Question.id == question_id).options(*_RELATIONS)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_ids(self, question_ids: list[uuid.UUID]) -> list[Question]:
        """Busca por lote de IDs, com relações carregadas.

        Reutilizado por `practice` para montar as questões de uma sessão de
        treino sem precisar de N+1 (uma questão por vez).
        """
        if not question_ids:
            return []
        stmt = select(Question).where(Question.id.in_(question_ids)).options(*_RELATIONS)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def count(self, filters: QuestionFilters) -> int:
        """Conta questões que casam com os filtros, sem paginar.

        Reaproveita `_apply_filters` — mesmo WHERE de `list_paginated`,
        trocando `SELECT *` por `func.count()`, então não carrega linhas,
        só a contagem. Usado para alimentar `meta.total` em
        `GET /api/v1/questions` (contador em tempo real no Banco de
        Questões). Ver `06_QUESTIONS_ENGINE.md` §4, opção (a) — reavaliar
        com `EXPLAIN ANALYZE` se a listagem ficar lenta com o crescimento
        da tabela.
        """
        stmt = select(func.count(Question.id))
        stmt = self._apply_filters(stmt, filters)  # type: ignore[arg-type]
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def facet_counts(
        self, dimension: str, filters: QuestionFilters
    ) -> list[tuple[object, int]]:
        """Contagem agregada de `dimension` (ex.: `discipline_id`, `year`)
        dentro do universo definido pelos filtros ATUAIS, exceto o próprio
        filtro de `dimension` (mesma semântica de facetas do Explorer:
        "se eu trocar só esta dimensão, quantas questões cada opção teria").

        Reaproveita `_apply_filters` (mesmo WHERE de `list_paginated`/`count`)
        — só troca `SELECT *` por `SELECT dimension, count(*) ... GROUP BY
        dimension`, então continua sem N+1 e sem trazer linhas de `Question`
        pra memória. Ver `QUESTOES_ENGINE_AUDIT.md` §5/§9 — este é o método
        que sustenta `GET /questions/facets`.
        """
        scoped_filters = replace(filters, **{dimension: None})
        dim_col = getattr(Question, dimension)
        stmt = select(dim_col, func.count(Question.id)).group_by(dim_col)
        stmt = self._apply_filters(stmt, scoped_filters)  # type: ignore[arg-type]
        result = await self.session.execute(stmt)
        return [(value, count) for value, count in result.all() if value is not None]

    async def list_random(self, filters: QuestionFilters, limit: int) -> list[Question]:
        """Seleciona até `limit` questões aleatórias que casam com os filtros.

        Usado para montar uma sessão de treino a partir de um conjunto de
        filtros. `ORDER BY random()` é aceitável no volume atual (milhares de
        questões); se a tabela crescer para a casa de milhões, revisitar com
        uma estratégia de amostragem mais barata (ex.: TABLESAMPLE).
        """
        stmt = select(Question).options(*_RELATIONS).order_by(func.random()).limit(limit)
        stmt = self._apply_filters(stmt, filters)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_paginated(
        self, limit: int, cursor_id: uuid.UUID | None, filters: QuestionFilters
    ) -> list[Question]:
        """Listagem paginada por keyset (created_at, id), com filtros e busca full-text."""
        stmt = (
            select(Question)
            .options(*_RELATIONS)
            .order_by(Question.created_at.asc(), Question.id.asc())
            .limit(limit)
        )
        stmt = self._apply_filters(stmt, filters)

        if cursor_id is not None:
            cursor_question = await self.get_by_id(cursor_id)
            if cursor_question is not None:
                stmt = stmt.where(
                    (Question.created_at > cursor_question.created_at)
                    | (
                        (Question.created_at == cursor_question.created_at)
                        & (Question.id > cursor_question.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())