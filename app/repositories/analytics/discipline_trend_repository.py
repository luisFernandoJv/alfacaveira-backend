"""Repositório de tendência por disciplina.

Diferente de `UserSubjectStatRepository` (que lê o agregado consolidado
`user_subject_stats`, sem recorte temporal), este repositório consulta
`question_attempts` diretamente -- a única fonte com granularidade de data
por resposta -- para comparar duas janelas de 15 dias (recente vs anterior)
e detectar se o aluno está melhorando, piorando ou estável em cada
disciplina.

É uma exceção deliberada à regra "services não leem tabela crua" que rege o
resto do módulo `analytics`: os agregados pré-calculados (`user_subject_stats`)
não guardam data, então não há como responder "como foram os últimos 15 dias"
sem consultar `question_attempts`. A consulta é uma única query agrupada
(não uma varredura por linha), então o custo é comparável a qualquer outro
relatório agregado.
"""

import uuid
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content.question import Question
from app.models.practice.question_attempt import QuestionAttempt


class DisciplineWindowStat:
    """Contagem de respostas/acertos de uma disciplina em uma janela de tempo."""

    __slots__ = ("discipline_id", "questions_answered", "correct_count")

    def __init__(self, discipline_id: uuid.UUID, questions_answered: int, correct_count: int) -> None:
        self.discipline_id = discipline_id
        self.questions_answered = questions_answered
        self.correct_count = correct_count

    @property
    def accuracy(self) -> float | None:
        if not self.questions_answered:
            return None
        return round(self.correct_count / self.questions_answered * 100, 1)


class DisciplineTrendRepository:
    """Agrega `question_attempts` por disciplina dentro de uma janela [start, end)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def window_stats_by_discipline(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> dict[uuid.UUID, DisciplineWindowStat]:
        """Total de respostas e acertos por disciplina no intervalo
        [start, end) de `answered_at`, para o usuário informado.

        Uma única query com JOIN + GROUP BY -- não varre `question_attempts`
        por linha em Python.
        """
        stmt = (
            select(
                Question.discipline_id,
                func.count(QuestionAttempt.id).label("total"),
                func.coalesce(
                    func.sum(case((QuestionAttempt.is_correct.is_(True), 1), else_=0)),
                    0,
                ).label("correct"),
            )
            .join(Question, Question.id == QuestionAttempt.question_id)
            .where(
                QuestionAttempt.user_id == user_id,
                QuestionAttempt.answered_at >= start,
                QuestionAttempt.answered_at < end,
            )
            .group_by(Question.discipline_id)
        )
        result = await self.session.execute(stmt)
        return {
            row.discipline_id: DisciplineWindowStat(row.discipline_id, int(row.total), int(row.correct))
            for row in result.all()
        }