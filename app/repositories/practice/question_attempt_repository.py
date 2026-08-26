"""Repositório de acesso a dados de `QuestionAttempt` (histórico de respostas)."""

import uuid
from datetime import datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.enums import SessionType
from app.models.practice.question_attempt import QuestionAttempt
from app.repositories.base import BaseRepository

_RELATIONS = (selectinload(QuestionAttempt.question),)


class QuestionAttemptRepository(BaseRepository[QuestionAttempt]):
    model = QuestionAttempt

    async def get_for_question_in_session(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
        session_type: SessionType,
        session_id: uuid.UUID,
    ) -> QuestionAttempt | None:
        """Tentativa já registrada para esta questão dentro desta sessão, se houver."""
        stmt = select(QuestionAttempt).where(
            QuestionAttempt.user_id == user_id,
            QuestionAttempt.question_id == question_id,
            QuestionAttempt.session_type == session_type,
            QuestionAttempt.session_id == session_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_correct_status_map(
        self, user_id: uuid.UUID, question_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, bool]:
        """Para cada `question_id` de `question_ids` já respondido pelo
        usuário, indica se ele acertou em ALGUMA tentativa (`True`) ou só
        errou em todas (`False`). Questões ausentes do dict não foram
        respondidas.

        ETAPA 3 (sessão 6): usado por `QuestionService.list_questions` para
        preencher `answer_status` na listagem, numa única query agregada em
        lote (evita N+1).
        """
        if not question_ids:
            return {}
        stmt = (
            select(
                QuestionAttempt.question_id,
                func.bool_or(QuestionAttempt.is_correct),
            )
            .where(
                QuestionAttempt.user_id == user_id,
                QuestionAttempt.question_id.in_(question_ids),
            )
            .group_by(QuestionAttempt.question_id)
        )
        result = await self.session.execute(stmt)
        return {row[0]: bool(row[1]) for row in result.all()}

    async def count_answered_today(
        self, user_id: uuid.UUID, session_type: SessionType
    ) -> int:
        """Quantidade de respostas do usuário hoje (UTC) para uma origem
        (`session_type`). Usado pelo Feature Gate de quota `daily_questions`
        — não conta respostas de outras origens (ex.: simulado tem seu
        próprio gate, `simulados`, e não compartilha a cota diária)."""
        today_start = datetime.combine(
            datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
        )
        stmt = select(func.count()).select_from(QuestionAttempt).where(
            QuestionAttempt.user_id == user_id,
            QuestionAttempt.session_type == session_type,
            QuestionAttempt.answered_at >= today_start,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_by_session(
        self, user_id: uuid.UUID, session_type: SessionType, session_id: uuid.UUID
    ) -> list[QuestionAttempt]:
        stmt = select(QuestionAttempt).where(
            QuestionAttempt.user_id == user_id,
            QuestionAttempt.session_type == session_type,
            QuestionAttempt.session_id == session_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_peer_aggregate(
        self, question_ids: list[uuid.UUID], exclude_user_id: uuid.UUID
    ) -> tuple[int, int, int]:
        """Agregado ANÔNIMO de todas as tentativas de outros usuários nas
        questões de `question_ids` — base da comparação "Demais usuários" na
        tela de resultado da sessão/caderno (item 2 do prompt).

        Retorna `(distinct_user_count, total_attempts, correct_attempts)`.
        Deliberadamente NÃO existe um `user_id` no retorno: a query só soma
        e conta linhas (`func.count`, `func.count(distinct ...)`), nunca
        seleciona `QuestionAttempt.user_id`, `selected_alternative_id` ou
        qualquer coluna que amarre um dado a uma pessoa específica — dá pra
        expor esse número no frontend sem vazar resposta nem identidade de
        ninguém, só o percentual médio da turma.

        `exclude_user_id` tira o próprio usuário da conta: o objetivo é
        comparar "eu" vs "os outros", não diluir a média dos outros com a
        tentativa de quem está vendo a tela.
        """
        if not question_ids:
            return (0, 0, 0)

        stmt = select(
            func.count(func.distinct(QuestionAttempt.user_id)),
            func.count(QuestionAttempt.id),
            func.count(QuestionAttempt.id).filter(QuestionAttempt.is_correct.is_(True)),
        ).where(
            QuestionAttempt.question_id.in_(question_ids),
            QuestionAttempt.user_id != exclude_user_id,
        )
        result = await self.session.execute(stmt)
        user_count, total_attempts, correct_attempts = result.one()
        return (user_count or 0, total_attempts or 0, correct_attempts or 0)

    async def list_paginated(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[QuestionAttempt]:
        """Histórico de respostas do usuário (qualquer origem), mais recentes primeiro."""
        stmt = (
            select(QuestionAttempt)
            .where(QuestionAttempt.user_id == user_id)
            .options(*_RELATIONS)
            .order_by(QuestionAttempt.answered_at.desc(), QuestionAttempt.id.desc())
            .limit(limit)
        )

        if cursor_id is not None:
            cursor_attempt = await self.get_by_id(cursor_id)
            if cursor_attempt is not None:
                stmt = stmt.where(
                    (QuestionAttempt.answered_at < cursor_attempt.answered_at)
                    | (
                        (QuestionAttempt.answered_at == cursor_attempt.answered_at)
                        & (QuestionAttempt.id < cursor_attempt.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())