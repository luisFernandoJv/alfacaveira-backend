"""Algoritmo SM-2 (SuperMemo 2) de repetição espaçada.

Implementação padrão do SM-2, parametrizada pela nota (0-5, "quality") que o
aluno dá ao revisar um cartão. `FlashcardGrade` (UI: Errei/Difícil/Bom/Fácil)
é mapeada para essa escala em `GRADE_TO_QUALITY` antes de chamar `sm2`.

Referência: https://super-memo.com/english/ol/sm2.htm
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.models.enums import FlashcardGrade

MIN_EASINESS_FACTOR = 1.3
DEFAULT_EASINESS_FACTOR = 2.5

GRADE_TO_QUALITY: dict[FlashcardGrade, int] = {
    FlashcardGrade.ERROU: 0,
    FlashcardGrade.DIFICIL: 3,
    FlashcardGrade.BOM: 4,
    FlashcardGrade.FACIL: 5,
}


@dataclass
class SM2State:
    """Estado de agendamento de um flashcard, antes ou depois de uma revisão."""

    easiness_factor: float
    interval_days: int
    repetitions: int


@dataclass
class SM2Result(SM2State):
    due_date: date


def sm2(current: SM2State, grade: FlashcardGrade, *, today: date | None = None) -> SM2Result:
    """Calcula o próximo estado (EF, intervalo, repetições, due_date) via SM-2.

    - `quality < 3` (grade ERROU): a resposta é considerada esquecida — zera as
      repetições e reinicia o ciclo de aprendizagem com intervalo de 1 dia.
    - `quality >= 3`: mantém a progressão de intervalos (1 → 6 → interval * EF)
      e incrementa as repetições. O EF é sempre recalculado pela fórmula
      original do SM-2 e nunca cai abaixo de `MIN_EASINESS_FACTOR`.
    """
    today = today or date.today()
    quality = GRADE_TO_QUALITY[grade]

    easiness_factor = current.easiness_factor + (
        0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    )
    easiness_factor = max(MIN_EASINESS_FACTOR, round(easiness_factor, 2))

    if quality < 3:
        repetitions = 0
        interval_days = 1
    else:
        repetitions = current.repetitions + 1
        if repetitions == 1:
            interval_days = 1
        elif repetitions == 2:
            interval_days = 6
        else:
            interval_days = max(1, round(current.interval_days * easiness_factor))

    return SM2Result(
        easiness_factor=easiness_factor,
        interval_days=interval_days,
        repetitions=repetitions,
        due_date=today + timedelta(days=interval_days),
    )
