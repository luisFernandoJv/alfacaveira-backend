"""Schemas de resposta de estatísticas agregadas do aluno (analytics).

`accuracy` é sempre calculada na camada de API a partir de `correct_count` e
`questions_answered` (nunca persistida) — evita as duas colunas divergirem
se um dia o worker gravar uma sem a outra.
"""

from datetime import date

from pydantic import BaseModel

from app.schemas.content.taxonomy import DisciplineResponse


class DailyStatResponse(BaseModel):
    """Um dia de atividade — usado na Evolução Semanal do Painel."""

    date: date
    questions_answered: int
    correct_count: int
    time_studied_seconds: int
    accuracy: float


class SubjectStatResponse(BaseModel):
    """Desempenho consolidado do usuário em uma disciplina."""

    discipline: DisciplineResponse
    questions_answered: int
    correct_count: int
    accuracy: float


class StreakResponse(BaseModel):
    """Sequência de dias estudados consecutivos."""

    current_streak: int
    longest_streak: int
    last_study_date: date | None


class TodayStatResponse(BaseModel):
    """Atividade do usuário no dia corrente. Zerada se ainda não estudou hoje."""

    questions_answered: int
    correct_count: int
    time_studied_seconds: int
    accuracy: float
