"""Regras de negócio de estatísticas agregadas do aluno (analytics).

Este service não deriva nenhum número a partir de `question_attempts` — ele
apenas lê os agregados já calculados pelo worker de background (que ainda
não existe, ver `app/workers`, vazio). Enquanto o worker não roda, os
métodos abaixo devolvem listas vazias / valores zerados, nunca dados
fictícios: é papel da camada HTTP (router) decidir como representar "sem
dado ainda" para o frontend.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics.user_stats import StudyStreak, UserDailyStat, UserSubjectStat
from app.repositories.analytics.discipline_trend_repository import DisciplineTrendRepository
from app.repositories.analytics.user_stats_repository import (
    StudyStreakRepository,
    UserDailyStatRepository,
    UserSubjectStatRepository,
)

# --- Constantes do Performance Score e das recomendações -------------------
# Documentadas aqui (não espalhadas pelo código) porque são a única parte
# deste service que expressa uma decisão de produto, não só uma leitura de
# dado. Qualquer ajuste de "o que conta como dado suficiente" muda aqui.

#: Volume vitalício mínimo de respostas para calcular o Performance Score.
#: Abaixo disso, `score` vai `None` — nunca um score bem-vindo tipo "todo
#: mundo começa em 50".
MIN_LIFETIME_QUESTIONS_FOR_SCORE = 10

#: Volume mínimo de respostas numa janela de 15 dias para essa janela contar
#: no cálculo de tendência por disciplina. Abaixo disso, a variação de
#: aproveitamento é ruído estatístico, não tendência.
MIN_ATTEMPTS_FOR_TREND = 5

#: Diferença mínima (pontos percentuais) de aproveitamento entre as duas
#: janelas de 15 dias para considerar "subiu"/"caiu" em vez de "estável".
TREND_THRESHOLD_PP = 3.0

#: Volume mínimo de respostas numa janela de 30 dias para essa janela contar
#: no cálculo da variação do score.
MIN_ATTEMPTS_FOR_SCORE_VARIATION = 5

#: Abaixo desse total de respostas no período analisado, uma disciplina em
#: faixa "Atenção" é tratada como "baixo volume" (recomendação de praticar
#: mais) em vez de deixada sem recomendação.
LOW_VOLUME_THRESHOLD = 20

#: Pesos do Performance Score (devem somar 1.0): aproveitamento (30d),
#: sequência de estudo atual (normalizada a 30 dias) e regularidade
#: (dias ativos nos últimos 30 dias / 30).
SCORE_WEIGHT_ACCURACY = 0.55
SCORE_WEIGHT_STREAK = 0.25
SCORE_WEIGHT_REGULARITY = 0.20

#: Pesos renormalizados (sem o componente de sequência, que é instantâneo e
#: não faz sentido recalculado para um período passado) usados só para
#: comparar dois períodos de 30 dias entre si na variação do score.
_VARIATION_WEIGHT_TOTAL = SCORE_WEIGHT_ACCURACY + SCORE_WEIGHT_REGULARITY
_VARIATION_WEIGHT_ACCURACY = SCORE_WEIGHT_ACCURACY / _VARIATION_WEIGHT_TOTAL
_VARIATION_WEIGHT_REGULARITY = SCORE_WEIGHT_REGULARITY / _VARIATION_WEIGHT_TOTAL


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total * 100, 1) if total else 0.0


@dataclass
class SubjectDashboardItem:
    """Uma linha de `UserSubjectStat` com tendência recente e status anexados."""

    stat: UserSubjectStat
    accuracy: float
    trend: str | None
    status: str


@dataclass
class RecommendationItem:
    discipline_id: uuid.UUID
    discipline_name: str
    priority: str
    reason: str


@dataclass
class DashboardBundle:
    """Resultado agregado de `AnalyticsService.get_dashboard`.

    Um dataclass puro (não o schema Pydantic de resposta) para manter a
    camada de service livre de detalhes de serialização HTTP -- é o router
    (`app/api/v1/analytics/dashboard.py`) que converte isto em
    `DashboardResponse`.
    """

    score: int | None
    score_variation_pct: float | None
    totals_lifetime_answered: int
    totals_lifetime_correct: int
    totals_lifetime_time_seconds: int
    streak: StudyStreak | None
    daily: list[UserDailyStat]
    subjects: list[SubjectDashboardItem] = field(default_factory=list)
    recommendations: list[RecommendationItem] = field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._daily = UserDailyStatRepository(session)
        self._subject = UserSubjectStatRepository(session)
        self._streak = StudyStreakRepository(session)
        self._trend = DisciplineTrendRepository(session)

    async def get_daily_stats(self, user_id: uuid.UUID, days: int) -> list[UserDailyStat]:
        """Estatísticas diárias dos últimos `days` dias (incluindo hoje).

        Dias sem nenhuma atividade não geram linha em `user_daily_stats` —
        a lista pode vir mais curta que `days`; cabe ao consumidor decidir
        se quer preencher os buracos com zero.
        """
        today = self._today()
        start = today - timedelta(days=days - 1)
        return await self._daily.list_between(user_id, start, today)

    async def get_today_stat(self, user_id: uuid.UUID) -> UserDailyStat | None:
        return await self._daily.get_for_date(user_id, self._today())

    async def get_subject_performance(self, user_id: uuid.UUID) -> list[UserSubjectStat]:
        return await self._subject.list_by_user(user_id)

    async def get_streak(self, user_id: uuid.UUID) -> StudyStreak | None:
        return await self._streak.get_by_user(user_id)

    async def get_dashboard(self, user_id: uuid.UUID, days: int) -> DashboardBundle:
        """Agregado único que alimenta a página de Desempenho.

        Consolida, em poucas queries, tudo que antes exigia 4 chamadas
        separadas (`/today` não entra aqui — ele é uma leitura pontual do
        dia corrente, sem relação com o Performance Score) mais o cálculo de
        score, variação e tendência por disciplina. Nenhum número é
        recalculado a partir de `question_attempts` além da tendência (ver
        `DisciplineTrendRepository`) — o resto vem direto dos agregados do
        worker.
        """
        today = self._today()
        period_start = today - timedelta(days=days - 1)

        daily, totals_lifetime, streak, subject_stats = await self._gather_base_data(
            user_id, period_start, today
        )

        subjects = await self._build_subject_items(user_id, subject_stats)
        score, variation = await self._compute_score(user_id, today, streak)
        recommendations = self._build_recommendations(subjects)

        answered, correct, seconds = totals_lifetime
        return DashboardBundle(
            score=score,
            score_variation_pct=variation,
            totals_lifetime_answered=answered,
            totals_lifetime_correct=correct,
            totals_lifetime_time_seconds=seconds,
            streak=streak,
            daily=daily,
            subjects=subjects,
            recommendations=recommendations,
            period_start=period_start,
            period_end=today,
        )

    async def _gather_base_data(
        self, user_id: uuid.UUID, period_start: date, today: date
    ) -> tuple[list[UserDailyStat], tuple[int, int, int], StudyStreak | None, list[UserSubjectStat]]:
        daily = await self._daily.list_between(user_id, period_start, today)
        totals_lifetime = await self._daily.sum_lifetime(user_id)
        streak = await self._streak.get_by_user(user_id)
        subject_stats = await self._subject.list_by_user(user_id)
        return daily, totals_lifetime, streak, subject_stats

    async def _build_subject_items(
        self, user_id: uuid.UUID, subject_stats: list[UserSubjectStat]
    ) -> list[SubjectDashboardItem]:
        """Anexa tendência (15d vs 15d anteriores) e status a cada disciplina.

        Tendência só é calculada quando ambas as janelas de 15 dias têm
        volume mínimo de respostas (`MIN_ATTEMPTS_FOR_TREND`) — senão vem
        `None`, e o frontend deve exibir "sem dado suficiente" em vez de uma
        seta.
        """
        if not subject_stats:
            return []

        now = datetime.now(UTC)
        recent_start = now - timedelta(days=15)
        prior_start = recent_start - timedelta(days=15)

        recent_by_discipline = await self._trend.window_stats_by_discipline(user_id, recent_start, now)
        prior_by_discipline = await self._trend.window_stats_by_discipline(
            user_id, prior_start, recent_start
        )

        items: list[SubjectDashboardItem] = []
        for stat in subject_stats:
            accuracy = _accuracy(stat.correct_count, stat.questions_answered)
            status = (
                "forte" if accuracy >= 80 else "atencao" if accuracy >= 60 else "prioridade"
            )

            recent = recent_by_discipline.get(stat.discipline_id)
            prior = prior_by_discipline.get(stat.discipline_id)
            trend: str | None = None
            if (
                recent
                and prior
                and recent.questions_answered >= MIN_ATTEMPTS_FOR_TREND
                and prior.questions_answered >= MIN_ATTEMPTS_FOR_TREND
                and recent.accuracy is not None
                and prior.accuracy is not None
            ):
                diff = recent.accuracy - prior.accuracy
                if diff > TREND_THRESHOLD_PP:
                    trend = "up"
                elif diff < -TREND_THRESHOLD_PP:
                    trend = "down"
                else:
                    trend = "stable"

            items.append(SubjectDashboardItem(stat=stat, accuracy=accuracy, trend=trend, status=status))

        return items

    async def _compute_score(
        self, user_id: uuid.UUID, today: date, streak: StudyStreak | None
    ) -> tuple[int | None, float | None]:
        """Performance Score (0-100) e sua variação nos últimos 30 dias.

        Fórmula: 55% aproveitamento (30d) + 25% sequência de estudo
        (normalizada a 30 dias) + 20% regularidade (dias ativos nos últimos
        30 dias / 30). Documentada aqui, não no frontend, porque é regra de
        negócio: qualquer mudança de peso é uma decisão de produto, não de
        exibição.
        """
        lifetime = await self._daily.sum_lifetime(user_id)
        if lifetime[0] < MIN_LIFETIME_QUESTIONS_FOR_SCORE:
            return None, None

        recent_answered, recent_correct, _seconds, recent_active = await self._daily.sum_window(
            user_id, today - timedelta(days=29), today
        )
        if recent_answered == 0:
            # Aluno tem histórico vitalício, mas nada nos últimos 30 dias:
            # não há como calcular um score que reflita o momento atual.
            return None, None

        accuracy_30d = _accuracy(recent_correct, recent_answered)
        current_streak = streak.current_streak if streak else 0
        streak_component = min(current_streak / 30, 1.0) * 100
        regularity_component = min(recent_active / 30, 1.0) * 100

        raw_score = (
            SCORE_WEIGHT_ACCURACY * accuracy_30d
            + SCORE_WEIGHT_STREAK * streak_component
            + SCORE_WEIGHT_REGULARITY * regularity_component
        )
        score = max(0, min(100, round(raw_score)))

        variation = await self._compute_score_variation(
            user_id, today, accuracy_30d, recent_active, recent_answered
        )
        return score, variation

    async def _compute_score_variation(
        self,
        user_id: uuid.UUID,
        today: date,
        accuracy_30d: float,
        recent_active: int,
        recent_answered: int,
    ) -> float | None:
        """Variação percentual entre os componentes comparáveis do score
        (aproveitamento + regularidade, sem a sequência) nos últimos 30 dias
        vs. os 30 dias imediatamente anteriores.

        `None` quando qualquer uma das duas janelas não tem volume mínimo de
        respostas (`MIN_ATTEMPTS_FOR_SCORE_VARIATION`).
        """
        if recent_answered < MIN_ATTEMPTS_FOR_SCORE_VARIATION:
            return None

        prev_answered, prev_correct, _seconds, prev_active = await self._daily.sum_window(
            user_id, today - timedelta(days=59), today - timedelta(days=30)
        )
        if prev_answered < MIN_ATTEMPTS_FOR_SCORE_VARIATION:
            return None

        prev_accuracy = _accuracy(prev_correct, prev_answered)
        recent_period_score = (
            _VARIATION_WEIGHT_ACCURACY * accuracy_30d
            + _VARIATION_WEIGHT_REGULARITY * min(recent_active / 30, 1.0) * 100
        )
        prior_period_score = (
            _VARIATION_WEIGHT_ACCURACY * prev_accuracy
            + _VARIATION_WEIGHT_REGULARITY * min(prev_active / 30, 1.0) * 100
        )
        if prior_period_score <= 0:
            return None
        return round((recent_period_score - prior_period_score) / prior_period_score * 100, 1)

    @staticmethod
    def _build_recommendations(subjects: list[SubjectDashboardItem]) -> list[RecommendationItem]:
        """Recomendações por regra objetiva — nenhuma IA, nenhuma heurística
        escondida. Só as três regras pedidas:

        - status "prioridade" + tendência de queda -> prioridade alta.
        - status "atenção" + baixo volume de respostas -> aumentar prática.
        - status "forte" + tendência de alta -> manutenção.

        Disciplinas que não se encaixam claramente em nenhuma regra (ex.:
        "atenção" com volume normal, ou tendência indisponível) não geram
        recomendação — é melhor não recomendar do que recomendar sem base.
        """
        priority_order = {"alta": 0, "aumentar_pratica": 1, "manutencao": 2}
        recommendations: list[RecommendationItem] = []

        for item in subjects:
            discipline = item.stat.discipline
            if item.status == "prioridade" and item.trend == "down":
                recommendations.append(
                    RecommendationItem(
                        discipline_id=discipline.id,
                        discipline_name=discipline.name,
                        priority="alta",
                        reason="Aproveitamento baixo e em queda nos últimos 15 dias.",
                    )
                )
            elif item.status == "atencao" and item.stat.questions_answered < LOW_VOLUME_THRESHOLD:
                recommendations.append(
                    RecommendationItem(
                        discipline_id=discipline.id,
                        discipline_name=discipline.name,
                        priority="aumentar_pratica",
                        reason="Aproveitamento médio com poucas questões respondidas até agora.",
                    )
                )
            elif item.status == "forte" and item.trend == "up":
                recommendations.append(
                    RecommendationItem(
                        discipline_id=discipline.id,
                        discipline_name=discipline.name,
                        priority="manutencao",
                        reason="Bom aproveitamento e em melhora — mantenha o ritmo atual.",
                    )
                )

        recommendations.sort(key=lambda r: priority_order[r.priority])
        return recommendations

    @staticmethod
    def _today() -> date:
        return datetime.now(UTC).date()