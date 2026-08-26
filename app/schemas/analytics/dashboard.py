"""Schemas de resposta do endpoint agregado `/analytics/dashboard`.

Consolida, em uma única resposta, tudo que a página de Desempenho precisa
para renderizar o Performance Score, a evolução, o desempenho por disciplina,
o mapa de domínio, os pontos de atenção e as recomendações -- sem introduzir
uma segunda fonte de verdade: todos os números aqui vêm dos mesmos agregados
(`user_daily_stats`, `user_subject_stats`, `study_streaks`) que os 4 endpoints
existentes já leem, mais uma consulta pontual de tendência sobre
`question_attempts` (ver `DisciplineTrendRepository`).

Qualquer campo que dependa de volume mínimo de dados vem `None` quando esse
volume não existe -- nunca um número estimado ou interpolado.
"""

import enum
import uuid
from datetime import date

from pydantic import BaseModel

from app.schemas.analytics.user_stats import DailyStatResponse, StreakResponse
from app.schemas.content.taxonomy import DisciplineResponse


class TrendDirection(str, enum.Enum):
    UP = "up"
    DOWN = "down"
    STABLE = "stable"


class SubjectStatus(str, enum.Enum):
    """Faixa de status por disciplina, por regra objetiva de aproveitamento.

    >=80% = FORTE · 60-79% = ATENCAO · <60% = PRIORIDADE.
    """

    FORTE = "forte"
    ATENCAO = "atencao"
    PRIORIDADE = "prioridade"


class RecommendationPriority(str, enum.Enum):
    ALTA = "alta"
    AUMENTAR_PRATICA = "aumentar_pratica"
    MANUTENCAO = "manutencao"


class DashboardScoreResponse(BaseModel):
    """Performance Score (0-100) e sua variação recente.

    `value` é `None` quando o aluno ainda não tem volume de respostas
    suficiente para um score representativo (ver regra em
    `AnalyticsService._compute_score`).

    `variation_pct` compara os componentes de aproveitamento + regularidade
    do score entre os últimos 30 dias e os 30 dias imediatamente anteriores
    (a sequência de estudo atual não entra nessa comparação, por ser um
    valor instantâneo, não uma métrica por período) -- é `None` quando
    qualquer uma das duas janelas não tem volume mínimo de respostas.
    """

    value: int | None
    variation_pct: float | None


class DashboardTotalsResponse(BaseModel):
    """Totais vitalícios reais do aluno na plataforma."""

    questions_answered: int
    correct_count: int
    time_studied_seconds: int
    accuracy: float


class DashboardSubjectResponse(BaseModel):
    """Desempenho por disciplina, com tendência recente e status objetivo."""

    discipline: DisciplineResponse
    questions_answered: int
    correct_count: int
    accuracy: float
    trend: TrendDirection | None
    status: SubjectStatus


class RecommendationResponse(BaseModel):
    """Recomendação gerada por regra objetiva a partir do desempenho por disciplina."""

    discipline_id: uuid.UUID
    discipline_name: str
    priority: RecommendationPriority
    reason: str


class DashboardResponse(BaseModel):
    score: DashboardScoreResponse
    totals_lifetime: DashboardTotalsResponse
    streak: StreakResponse
    daily: list[DailyStatResponse]
    subjects: list[DashboardSubjectResponse]
    recommendations: list[RecommendationResponse]
    period_start: date | None
    period_end: date | None