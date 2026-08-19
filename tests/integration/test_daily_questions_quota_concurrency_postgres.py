"""Concorrência real contra Postgres para a quota diária `daily_questions`
(Free = 5 questões/dia), fechando o item 29 da auditoria do funil comercial
(Free/Padrão/Pro): o limite precisa ser seguro contra requisições
simultâneas — duas respostas concorrentes não podem juntas furar o limite
(5 -> 6/7).

Mesmo padrão de `test_subscription_concurrency_postgres.py`: duas
`AsyncSession` independentes, cada uma sua própria conexão do `db_engine`
(não `db_session`, que roda numa única transação externa e não simula duas
transações committadas de verdade), disputam a MESMA quota via
`QuestionAttemptService.submit_training_answer` disparadas com
`asyncio.gather`.

A proteção é um `pg_advisory_xact_lock` por usuário dentro do mesmo
`UnitOfWork` que faz a contagem + o insert do `QuestionAttempt` (ver
`app/services/practice/question_attempt_repository.py`) — sob essa lock, a
segunda chamada só conta depois que a primeira commitou, então já enxerga o
attempt recém-inserido.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import ForbiddenError
from app.models.content.exam_source import ExamBoard
from app.models.content.question import Question, QuestionAlternative
from app.models.content.taxonomy import Discipline
from app.models.enums import QuestionDifficulty, QuestionStatus, SessionType
from app.models.identity.user import User
from app.models.practice.question_attempt import QuestionAttempt
from app.models.practice.training_session import TrainingSession, TrainingSessionQuestion
from app.schemas.practice.question_attempt import AnswerSubmitRequest
from app.security.password import hash_password
from app.services.practice.question_attempt_repository import QuestionAttemptService

pytestmark = pytest.mark.asyncio

# Quota do plano Free (`daily_questions`), seedada por
# `migrations/versions/0006_seed_billing_catalog.py`. Um usuário sem
# assinatura ativa cai no Free por convenção (`FeatureGateService`).
FREE_DAILY_QUESTIONS_LIMIT = 5


def _session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


async def _seed_user_with_answered_questions(
    session: AsyncSession, *, already_answered: int, extra_unanswered: int
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """Cria um usuário Free (sem subscription) com `already_answered`
    `QuestionAttempt`s já registrados HOJE, uma `TrainingSession` aberta e
    `extra_unanswered` questões novas na sessão (uma por chamada
    concorrente do teste). Retorna (user_id, session_id, question_ids das
    ainda não respondidas).
    """
    now = datetime.now(UTC)

    user = User(
        email=f"{uuid.uuid4()}@teste.local",
        password_hash=hash_password("senha-teste-123"),
        full_name="Aluno Free de Teste",
        is_active=True,
    )
    discipline = Discipline(name=f"Disciplina {uuid.uuid4()}", slug=f"disciplina-{uuid.uuid4()}")
    exam_board = ExamBoard(
        name=f"Banca {uuid.uuid4()}", acronym=str(uuid.uuid4())[:8], slug=f"banca-{uuid.uuid4()}"
    )
    session.add_all([user, discipline, exam_board])
    await session.flush()

    total_questions = already_answered + extra_unanswered
    questions: list[Question] = []
    for i in range(total_questions):
        question = Question(
            discipline_id=discipline.id,
            exam_board_id=exam_board.id,
            difficulty=QuestionDifficulty.MEDIA,
            status=QuestionStatus.PUBLICADA,
            statement=f"Enunciado de teste {i} — {uuid.uuid4()}",
            correct_alternative_letter="A",
        )
        questions.append(question)
    session.add_all(questions)
    await session.flush()

    for question in questions:
        session.add(
            QuestionAlternative(question_id=question.id, letter="A", text="Certa", is_correct=True)
        )
        session.add(
            QuestionAlternative(question_id=question.id, letter="B", text="Errada", is_correct=False)
        )
    await session.flush()

    training_session = TrainingSession(
        user_id=user.id,
        filters_snapshot={},
        total_questions=total_questions,
        started_at=now,
    )
    session.add(training_session)
    await session.flush()

    for position, question in enumerate(questions):
        session.add(
            TrainingSessionQuestion(session_id=training_session.id, question_id=question.id, position=position)
        )
    await session.flush()

    # Registra as respostas "já dadas hoje" diretamente (sem passar pelo
    # service — só queremos preencher `answered_today` até perto do limite).
    for question in questions[:already_answered]:
        session.add(
            QuestionAttempt(
                user_id=user.id,
                question_id=question.id,
                session_type=SessionType.TREINO,
                session_id=training_session.id,
                selected_alternative_id=None,
                is_correct=False,
            )
        )
    await session.commit()

    unanswered_ids = [q.id for q in questions[already_answered:]]
    return user.id, training_session.id, unanswered_ids


async def _count_attempts_today(session: AsyncSession, user_id: uuid.UUID) -> int:
    stmt = select(QuestionAttempt).where(QuestionAttempt.user_id == user_id)
    result = await session.execute(stmt)
    return len(result.scalars().all())


class TestDailyQuestionsQuotaConcurrencyReal:
    async def test_two_concurrent_answers_at_the_limit_only_one_succeeds(
        self, db_engine: AsyncEngine
    ) -> None:
        """Usuário Free já respondeu 4/5 hoje. Duas respostas concorrentes
        disputam a 5ª vaga — exatamente uma deve ser aceita (chegando a
        5/5) e a outra deve ser bloqueada com `ForbiddenError` (limite
        atingido), nunca as duas passando (o que furaria para 6/5).
        """
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            user_id, session_id, unanswered_ids = await _seed_user_with_answered_questions(
                seed_session,
                already_answered=FREE_DAILY_QUESTIONS_LIMIT - 1,
                extra_unanswered=2,
            )

        async with factory() as s1, factory() as s2:
            service_a = QuestionAttemptService(s1)
            service_b = QuestionAttemptService(s2)

            data = AnswerSubmitRequest(selected_alternative_id=None, time_spent_seconds=10)

            results = await asyncio.gather(
                service_a.submit_training_answer(user_id, session_id, unanswered_ids[0], data),
                service_b.submit_training_answer(user_id, session_id, unanswered_ids[1], data),
                return_exceptions=True,
            )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 1, "exatamente uma das duas respostas concorrentes deve ser aceita"
        assert len(failures) == 1
        assert isinstance(failures[0], ForbiddenError)

        async with factory() as check_session:
            total_today = await _count_attempts_today(check_session, user_id)
        assert total_today == FREE_DAILY_QUESTIONS_LIMIT, (
            "o total de respostas de hoje nunca pode ultrapassar o limite do plano Free "
            f"(esperado {FREE_DAILY_QUESTIONS_LIMIT}, obtido {total_today})"
        )
