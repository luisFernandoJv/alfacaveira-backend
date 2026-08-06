"""Worker de agregação do módulo `analytics`.

Lê `question_attempts` (fonte de verdade, tabela crua) e recalcula os
agregados que os endpoints de `analytics` leem (`user_daily_stats`,
`user_subject_stats`, `study_streaks`) — ver docstring de
`app/models/analytics/user_stats.py` e `app/services/analytics/analytics_service.py`.

Idempotente por construção: cada agregado é gravado via upsert (nunca
incrementado), então rodar o worker duas vezes sobre o mesmo período dá
exatamente o mesmo resultado — importante porque não há garantia de
exactly-once na forma como isso será agendado.

Não existe fila/agendador no projeto ainda (`docs/architecture.md` não
lista Celery/APScheduler — só Redis para rate limit). Enquanto isso não
existir, este módulo é pensado para ser chamado por um cron externo (ex.:
cron do próprio host, ou um scheduled job do provedor de hospedagem),
seguindo o mesmo padrão de script standalone já usado em
`scripts/seed_test_data.py`:

    poetry run python -m app.workers.analytics_aggregator
    poetry run python -m app.workers.analytics_aggregator --days 30

Recomendação: rodar a cada poucos minutos (ex.: a cada 5-15 min) com
`--days 2` (hoje + ontem, cobre fuso horário e execuções atrasadas) para
`user_daily_stats`/streak ficarem quase em tempo real, e 1x/dia com uma
janela maior para reconciliar eventuais falhas.
"""

import argparse
import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionFactory
from app.models.analytics.user_stats import StudyStreak, UserDailyStat, UserSubjectStat
from app.models.content.question import Question
from app.models.practice.question_attempt import QuestionAttempt


async def _recompute_daily_stats(session: AsyncSession, start_date: date, end_date: date) -> None:
    """Recalcula `user_daily_stats` para o intervalo [start_date, end_date].

    Só esta janela é reprocessada a cada execução (não a tabela inteira) —
    é o que permite rodar o worker com frequência alta sem varrer todo o
    histórico de `question_attempts` toda vez.
    """
    stmt = (
        select(
            QuestionAttempt.user_id,
            func.date(QuestionAttempt.answered_at).label("day"),
            func.count().label("questions_answered"),
            func.sum(case((QuestionAttempt.is_correct.is_(True), 1), else_=0)).label(
                "correct_count"
            ),
            func.coalesce(func.sum(QuestionAttempt.time_spent_seconds), 0).label(
                "time_studied_seconds"
            ),
        )
        .where(
            QuestionAttempt.answered_at >= start_date,
            QuestionAttempt.answered_at < end_date + timedelta(days=1),
        )
        .group_by(QuestionAttempt.user_id, func.date(QuestionAttempt.answered_at))
    )

    rows = (await session.execute(stmt)).all()
    for row in rows:
        insert_stmt = pg_insert(UserDailyStat).values(
            user_id=row.user_id,
            date=row.day,
            questions_answered=row.questions_answered,
            correct_count=int(row.correct_count),
            time_studied_seconds=int(row.time_studied_seconds),
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["user_id", "date"],
            set_={
                "questions_answered": insert_stmt.excluded.questions_answered,
                "correct_count": insert_stmt.excluded.correct_count,
                "time_studied_seconds": insert_stmt.excluded.time_studied_seconds,
            },
        )
        await session.execute(upsert_stmt)


async def _recompute_subject_stats(session: AsyncSession) -> None:
    """Recalcula `user_subject_stats` — sempre o histórico completo.

    Diferente de `user_daily_stats`, não dá para janelar por período (o
    dado é um acumulado "desde sempre" por disciplina). Enquanto o volume
    de `question_attempts` for pequeno isso é barato; é o primeiro
    candidato a revisão (ex.: manter um acumulado incremental por usuário
    em vez de recontar tudo) se o produto crescer bastante.
    """
    stmt = (
        select(
            QuestionAttempt.user_id,
            Question.discipline_id,
            func.count().label("questions_answered"),
            func.sum(case((QuestionAttempt.is_correct.is_(True), 1), else_=0)).label(
                "correct_count"
            ),
        )
        .join(Question, Question.id == QuestionAttempt.question_id)
        .group_by(QuestionAttempt.user_id, Question.discipline_id)
    )
    rows = (await session.execute(stmt)).all()
    now = datetime.now(UTC)

    for row in rows:
        insert_stmt = pg_insert(UserSubjectStat).values(
            user_id=row.user_id,
            discipline_id=row.discipline_id,
            questions_answered=row.questions_answered,
            correct_count=int(row.correct_count),
            updated_at=now,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["user_id", "discipline_id"],
            set_={
                "questions_answered": insert_stmt.excluded.questions_answered,
                "correct_count": insert_stmt.excluded.correct_count,
                "updated_at": insert_stmt.excluded.updated_at,
            },
        )
        await session.execute(upsert_stmt)


async def _recompute_streaks(session: AsyncSession) -> None:
    """Recalcula `study_streaks` a partir dos dias com atividade já em `user_daily_stats`.

    Sequência = dias consecutivos com `questions_answered > 0`; a atual só é
    considerada "viva" se o último dia estudado foi hoje ou ontem (pular um
    dia inteiro zera). `longest_streak` nunca regride entre execuções — o
    upsert usa `GREATEST` contra o valor já gravado, então um streak recorde
    não some se o usuário parar de estudar depois.

    O cálculo é feito em Python sobre as datas já agregadas (não em SQL) —
    mais simples de ler e testar; se o número de usuários crescer muito,
    vale revisar para uma window function no banco.
    """
    stmt = (
        select(UserDailyStat.user_id, UserDailyStat.date)
        .where(UserDailyStat.questions_answered > 0)
        .order_by(UserDailyStat.user_id, UserDailyStat.date)
    )
    rows = (await session.execute(stmt)).all()

    dates_by_user: dict[uuid.UUID, list[date]] = defaultdict(list)
    for row in rows:
        dates_by_user[row.user_id].append(row.date)

    today = datetime.now(UTC).date()

    for user_id, study_dates in dates_by_user.items():
        longest = 1
        current_run = 1
        for previous, current in zip(study_dates, study_dates[1:]):
            if (current - previous).days == 1:
                current_run += 1
            else:
                longest = max(longest, current_run)
                current_run = 1
        longest = max(longest, current_run)

        last_date = study_dates[-1]
        current_streak = current_run if (today - last_date).days <= 1 else 0

        insert_stmt = pg_insert(StudyStreak).values(
            user_id=user_id,
            current_streak=current_streak,
            longest_streak=longest,
            last_study_date=last_date,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "current_streak": insert_stmt.excluded.current_streak,
                "longest_streak": func.greatest(
                    StudyStreak.longest_streak, insert_stmt.excluded.longest_streak
                ),
                "last_study_date": insert_stmt.excluded.last_study_date,
            },
        )
        await session.execute(upsert_stmt)


async def run(days: int = 7) -> None:
    """Ponto de entrada do worker.

    `days` controla só a janela reprocessada em `user_daily_stats`;
    `user_subject_stats` e `study_streaks` sempre olham o acumulado
    completo, pois dependem de tudo, não de uma janela recente.
    """
    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=days - 1)

    async with AsyncSessionFactory() as session:
        await _recompute_daily_stats(session, start_date, today)
        await _recompute_subject_stats(session)
        await _recompute_streaks(session)
        await session.commit()

    print(f"Agregação concluída (janela: {start_date.isoformat()} a {today.isoformat()}).")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recalcula os agregados lidos pelo módulo analytics."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Janela em dias reprocessada em user_daily_stats (padrão: 7).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(run(days=args.days))
