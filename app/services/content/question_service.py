"""Regras de negócio de questões: CRUD (admin), listagem pública filtrável e
histórico de alterações (auditoria append-only via `QuestionRevision`).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database.uow import UnitOfWork
from app.models.content.question import Question, QuestionAlternative
from app.models.content.question_revision import QuestionRevision
from app.models.enums import QuestionAnswerStatus, QuestionRevisionType, QuestionStatus
from app.repositories.content.exam_source_repository import ExamBoardRepository
from app.repositories.content.question_repository import QuestionFilters, QuestionRepository
from app.repositories.content.question_tag_repository import QuestionTagRepository
from app.repositories.content.taxonomy_repository import DisciplineRepository
from app.repositories.practice.question_attempt_repository import QuestionAttemptRepository
from app.repositories.practice.user_question_state_repository import (
    UserQuestionStateRepository,
)
from app.schemas.content.question import QuestionCreateRequest, QuestionUpdateRequest


def _snapshot(question: Question) -> dict[str, object]:
    """Monta o snapshot (JSONB) gravado em `QuestionRevision` a cada mudança."""
    return {
        "discipline_id": str(question.discipline_id),
        "subject_id": str(question.subject_id) if question.subject_id else None,
        "topic_id": str(question.topic_id) if question.topic_id else None,
        "exam_board_id": str(question.exam_board_id),
        "exam_edition_id": str(question.exam_edition_id) if question.exam_edition_id else None,
        "organization_id": str(question.organization_id) if question.organization_id else None,
        "year": question.year,
        "difficulty": question.difficulty.value,
        "status": question.status.value,
        "statement": question.statement,
        "explanation": question.explanation,
        "correct_alternative_letter": question.correct_alternative_letter,
        "alternatives": [
            {"letter": alt.letter, "text": alt.text, "is_correct": alt.is_correct}
            for alt in question.alternatives
        ],
        "tag_ids": [str(tag.id) for tag in question.tags],
    }


class QuestionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._questions = QuestionRepository(session)
        self._disciplines = DisciplineRepository(session)
        self._exam_boards = ExamBoardRepository(session)
        self._tags = QuestionTagRepository(session)
        self._states = UserQuestionStateRepository(session)
        self._attempts = QuestionAttemptRepository(session)

    async def get_question(self, question_id: uuid.UUID) -> Question:
        question = await self._questions.get_with_relations(question_id)
        if question is None:
            raise NotFoundError("Questão não encontrada.")
        return question

    async def list_questions(
        self,
        limit: int,
        cursor_id: uuid.UUID | None,
        filters: QuestionFilters,
        user_id: uuid.UUID | None = None,
    ) -> list[Question]:
        """Lista pública e filtrável de questões.

        ETAPA 3 (sessão 6): quando `user_id` é informado (sempre é, na
        prática — o endpoint exige `CurrentUser`), cada `Question` retornada
        ganha dois atributos transientes (não persistidos, só para a
        resposta): `is_favorite` e `answer_status`, calculados em lote a
        partir de `UserQuestionState`/`QuestionAttempt` — sem N+1 (duas
        queries extras no total, independente da quantidade de questões da
        página). `QuestionListItem.model_validate` lê esses atributos via
        `from_attributes=True`.
        ETAPA 4 (auditoria Banco de Questões, 2026-08-14): `filters.user_id`
        é preenchido aqui (não pela rota) porque o mesmo `user_id` que
        preenche `is_favorite`/`answer_status` na resposta agora também é
        necessário para o filtro real de `answer_status` no banco
        (`QuestionRepository._apply_filters`) — evita passar o mesmo dado
        duas vezes por dois caminhos diferentes.
        """
        filters.user_id = user_id
        questions = await self._questions.list_paginated(
            limit=limit, cursor_id=cursor_id, filters=filters
        )
        if user_id is None or not questions:
            for question in questions:
                question.is_favorite = False
                question.answer_status = QuestionAnswerStatus.NAO_RESPONDIDA
            return questions

        question_ids = [q.id for q in questions]
        favorited_ids, correct_map = await self._session_gather(
            self._states.get_favorited_ids(user_id, question_ids),
            self._attempts.get_correct_status_map(user_id, question_ids),
        )

        for question in questions:
            question.is_favorite = question.id in favorited_ids
            if question.id not in correct_map:
                question.answer_status = QuestionAnswerStatus.NAO_RESPONDIDA
            elif correct_map[question.id]:
                question.answer_status = QuestionAnswerStatus.ACERTOU
            else:
                question.answer_status = QuestionAnswerStatus.ERROU

        return questions

    async def count_questions(
        self, filters: QuestionFilters, user_id: uuid.UUID | None = None
    ) -> int:
        """Total de questões que casam com os filtros, sem paginar.

        Mesmos filtros de `list_questions` — incluindo `answer_status`/
        `favorite_only`, que exigem `user_id` (ver
        `QuestionRepository._apply_filters`). Usado para expor
        `meta.total` em `GET /api/v1/questions` (contador em tempo real
        no Banco de Questões).
        """
        filters.user_id = user_id
        return await self._questions.count(filters)

    @staticmethod
    async def _session_gather(*coros):
        """Executa as duas queries de estado em sequência.

        Não usamos `asyncio.gather` aqui de propósito: as duas coroutines
        compartilham a MESMA `AsyncSession` do SQLAlchemy, que não é
        concorrente — rodar em paralelo geraria erro/corrupção de estado da
        sessão. Sequencial é a forma segura de "aguardar as duas".
        """
        results = []
        for coro in coros:
            results.append(await coro)
        return results

    async def create_question(
        self, admin_user_id: uuid.UUID, data: QuestionCreateRequest
    ) -> Question:
        if await self._disciplines.get_by_id(data.discipline_id) is None:
            raise NotFoundError("Disciplina não encontrada.")
        if await self._exam_boards.get_by_id(data.exam_board_id) is None:
            raise NotFoundError("Banca examinadora não encontrada.")

        tags = []
        if data.tag_ids:
            tags = await self._tags.list_by_ids(data.tag_ids)
            if len(tags) != len(set(data.tag_ids)):
                raise NotFoundError("Uma ou mais tags não foram encontradas.")

        correct = next(alt for alt in data.alternatives if alt.is_correct)
        question = Question(
            discipline_id=data.discipline_id,
            subject_id=data.subject_id,
            topic_id=data.topic_id,
            exam_board_id=data.exam_board_id,
            exam_edition_id=data.exam_edition_id,
            organization_id=data.organization_id,
            year=data.year,
            difficulty=data.difficulty,
            status=QuestionStatus.RASCUNHO,
            statement=data.statement,
            explanation=data.explanation,
            correct_alternative_letter=correct.letter,
            created_by=admin_user_id,
        )
        question.alternatives = [
            QuestionAlternative(letter=alt.letter, text=alt.text, is_correct=alt.is_correct)
            for alt in data.alternatives
        ]
        question.tags = tags

        async with UnitOfWork(self._session):
            await self._questions.add(question)
            self._session.add(
                QuestionRevision(
                    question_id=question.id,
                    changed_by=admin_user_id,
                    change_type=QuestionRevisionType.CRIACAO,
                    snapshot=_snapshot(question),
                )
            )

        return await self.get_question(question.id)

    async def update_question(
        self, question_id: uuid.UUID, admin_user_id: uuid.UUID, data: QuestionUpdateRequest
    ) -> Question:
        question = await self.get_question(question_id)

        fields = data.model_dump(exclude_unset=True, exclude={"alternatives", "tag_ids"})
        if "discipline_id" in fields:
            discipline = await self._disciplines.get_by_id(fields["discipline_id"])
            if discipline is None:
                raise NotFoundError("Disciplina não encontrada.")
        if "exam_board_id" in fields:
            exam_board = await self._exam_boards.get_by_id(fields["exam_board_id"])
            if exam_board is None:
                raise NotFoundError("Banca examinadora não encontrada.")

        new_tags = None
        if data.tag_ids is not None:
            new_tags = await self._tags.list_by_ids(data.tag_ids)
            if len(new_tags) != len(set(data.tag_ids)):
                raise NotFoundError("Uma ou mais tags não foram encontradas.")

        async with UnitOfWork(self._session):
            for field, value in fields.items():
                setattr(question, field, value)

            if data.alternatives is not None:
                correct = next(alt for alt in data.alternatives if alt.is_correct)
                question.alternatives = [
                    QuestionAlternative(letter=alt.letter, text=alt.text, is_correct=alt.is_correct)
                    for alt in data.alternatives
                ]
                question.correct_alternative_letter = correct.letter

            if new_tags is not None:
                question.tags = new_tags

            await self._session.flush()
            self._session.add(
                QuestionRevision(
                    question_id=question.id,
                    changed_by=admin_user_id,
                    change_type=QuestionRevisionType.EDICAO,
                    snapshot=_snapshot(question),
                )
            )

        return await self.get_question(question.id)

    async def update_status(
        self, question_id: uuid.UUID, admin_user_id: uuid.UUID, new_status: QuestionStatus
    ) -> Question:
        question = await self.get_question(question_id)

        async with UnitOfWork(self._session):
            question.status = new_status
            await self._session.flush()
            self._session.add(
                QuestionRevision(
                    question_id=question.id,
                    changed_by=admin_user_id,
                    change_type=QuestionRevisionType.STATUS,
                    snapshot=_snapshot(question),
                )
            )

        return await self.get_question(question.id)

    async def delete_question(self, question_id: uuid.UUID, admin_user_id: uuid.UUID) -> None:
        """Exclusão lógica: marca `status = DESATIVADA` e registra a revisão.

        Nunca faz `DELETE` físico — isso apagaria em cascata o próprio
        histórico de auditoria (`question_revisions`, FK `ON DELETE CASCADE`),
        o que contraria o propósito de uma trilha append-only.
        """
        question = await self.get_question(question_id)

        async with UnitOfWork(self._session):
            question.status = QuestionStatus.DESATIVADA
            await self._session.flush()
            self._session.add(
                QuestionRevision(
                    question_id=question.id,
                    changed_by=admin_user_id,
                    change_type=QuestionRevisionType.EXCLUSAO,
                    snapshot=_snapshot(question),
                )
            )