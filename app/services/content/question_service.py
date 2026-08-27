"""Regras de negócio de questões: CRUD (admin), listagem pública filtrável e
histórico de alterações (auditoria append-only via `QuestionRevision`).
"""

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MAX_BULK_QUESTION_SELECTION
from app.core.exceptions import ConflictError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.content.question import Question, QuestionAlternative
from app.models.content.question_attachment import QuestionAttachment
from app.models.content.question_revision import QuestionRevision
from app.models.enums import AttachmentType, QuestionAnswerStatus, QuestionRevisionType, QuestionStatus
from app.repositories.content.exam_source_repository import (
    ExamBoardRepository,
    ExamEditionRepository,
    OrganizationRepository,
)
from app.repositories.content.question_repository import QuestionFilters, QuestionRepository
from app.repositories.content.question_tag_repository import QuestionTagRepository
from app.repositories.content.taxonomy_repository import (
    DisciplineRepository,
    SubjectRepository,
    TopicRepository,
)
from app.repositories.practice.question_attempt_repository import QuestionAttemptRepository
from app.repositories.practice.user_question_state_repository import (
    UserQuestionStateRepository,
)
from app.schemas.content.question import QuestionCreateRequest, QuestionUpdateRequest

logger = structlog.get_logger(__name__)


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
        "teacher_name": question.teacher_name,
        "correct_alternative_letter": question.correct_alternative_letter,
        "alternatives": [
            {
                "letter": alt.letter,
                "text": alt.text,
                "is_correct": alt.is_correct,
                "image_url": alt.image_url,
            }
            for alt in question.alternatives
        ],
        "tag_ids": [str(tag.id) for tag in question.tags],
        "attachments": [
            {"type": att.type.value, "url": att.url, "alt_text": att.alt_text}
            for att in question.attachments
        ],
    }


class QuestionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._questions = QuestionRepository(session)
        self._disciplines = DisciplineRepository(session)
        self._subjects = SubjectRepository(session)
        self._topics = TopicRepository(session)
        self._exam_boards = ExamBoardRepository(session)
        self._exam_editions = ExamEditionRepository(session)
        self._organizations = OrganizationRepository(session)
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

    # Dimensões facetáveis expostas por `GET /questions/facets`. Mantidas
    # como tupla (não `QuestionFilters.__dataclass_fields__` genérico) de
    # propósito — nem todo campo de filtro faz sentido como faceta (ex.:
    # `search`/`answer_status`/`favorite_only` continuam sendo filtros
    # aplicados normalmente ao universo, só não são "contados por opção").
    FACET_DIMENSIONS = (
        "discipline_id",
        "subject_id",
        "topic_id",
        "exam_board_id",
        "organization_id",
        "year",
        "difficulty",
    )

    async def get_facets(
        self, filters: QuestionFilters, user_id: uuid.UUID | None = None
    ) -> dict[str, object]:
        """Total filtrado + contagem por opção de cada dimensão facetável.

        Sequencial de propósito (mesma `AsyncSession`, não é concorrente —
        ver `_session_gather`): 1 query de total + 1 query agregada por
        dimensão. Nenhuma delas carrega linhas de `Question` pra memória.
        """
        filters.user_id = user_id
        total = await self.count_questions(filters=filters, user_id=user_id)

        facets: dict[str, list[dict[str, object]]] = {}
        for dimension in self.FACET_DIMENSIONS:
            rows = await self._questions.facet_counts(dimension, filters)
            facets[dimension] = [
                {"id": str(value.value if hasattr(value, "value") else value), "count": count}
                for value, count in rows
            ]

        return {"total": total, **facets}

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

    async def list_question_ids(
        self,
        filters: QuestionFilters,
        user_id: uuid.UUID | None = None,
        limit: int = MAX_BULK_QUESTION_SELECTION,
    ) -> list[uuid.UUID]:
        """IDs (só isso, sem relações) que casam com os filtros — usado por
        'selecionar tudo' no Banco de Questões. Se o total filtrado passar
        de `limit`, o front avisa o usuário (não é um erro silencioso).
        """
        filters.user_id = user_id
        return await self._questions.list_ids(filters, limit=limit)

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
            teacher_name=data.teacher_name,
            correct_alternative_letter=correct.letter,
            created_by=admin_user_id,
        )
        question.alternatives = [
            QuestionAlternative(
                letter=alt.letter,
                text=alt.text,
                is_correct=alt.is_correct,
                image_url=alt.image_url,
            )
            for alt in data.alternatives
        ]
        question.tags = tags
        question.attachments = [
            QuestionAttachment(
                type=AttachmentType(att.type), url=att.url, alt_text=att.alt_text
            )
            for att in data.attachments
        ]

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

        fields = data.model_dump(
            exclude_unset=True, exclude={"alternatives", "tag_ids", "attachments"}
        )

        # 🔥 CORREÇÃO (500 genérico ao salvar na tela "Conferir questões"):
        # a tela passou a permitir editar disciplina/assunto/banca/dificuldade
        # no mesmo PATCH que já editava enunciado/alternativas, mas só
        # `discipline_id`/`exam_board_id` eram validados aqui. Um
        # `subject_id`/`topic_id`/`exam_edition_id`/`organization_id` que não
        # existisse (ou não existisse mais) só era percebido no `flush()`
        # como um `IntegrityError` de FK, sem handler — virava um 500 sem
        # explicação nenhuma para o admin. Agora todo campo de referência
        # opcional é validado antes de tocar no objeto, com um 404 legível.
        if "discipline_id" in fields and fields["discipline_id"] is not None:
            if await self._disciplines.get_by_id(fields["discipline_id"]) is None:
                raise NotFoundError("Disciplina não encontrada.")
        if "exam_board_id" in fields and fields["exam_board_id"] is not None:
            if await self._exam_boards.get_by_id(fields["exam_board_id"]) is None:
                raise NotFoundError("Banca examinadora não encontrada.")
        if "subject_id" in fields and fields["subject_id"] is not None:
            if await self._subjects.get_by_id(fields["subject_id"]) is None:
                raise NotFoundError("Assunto não encontrado.")
        if "topic_id" in fields and fields["topic_id"] is not None:
            if await self._topics.get_by_id(fields["topic_id"]) is None:
                raise NotFoundError("Subassunto não encontrado.")
        if "exam_edition_id" in fields and fields["exam_edition_id"] is not None:
            if await self._exam_editions.get_by_id(fields["exam_edition_id"]) is None:
                raise NotFoundError("Edição de concurso não encontrada.")
        if "organization_id" in fields and fields["organization_id"] is not None:
            if await self._organizations.get_by_id(fields["organization_id"]) is None:
                raise NotFoundError("Órgão não encontrado.")

        new_tags = None
        if data.tag_ids is not None:
            new_tags = await self._tags.list_by_ids(data.tag_ids)
            if len(new_tags) != len(set(data.tag_ids)):
                raise NotFoundError("Uma ou mais tags não foram encontradas.")

        try:
            async with UnitOfWork(self._session):
                for field, value in fields.items():
                    setattr(question, field, value)

                if data.alternatives is not None:
                    # 🔥 CORREÇÃO REAL do 500/409 ao salvar (a causa raiz
                    # não era nenhuma FK de taxonomia): `question.alternatives
                    # = [novas instâncias...]` agenda DELETE das antigas +
                    # INSERT das novas via cascade "all, delete-orphan". O
                    # SQLAlchemy SEMPRE executa todos os INSERTs antes de
                    # todos os DELETEs num mesmo flush (comportamento
                    # documentado do Unit of Work, não uma corrida). Como
                    # existe `UniqueConstraint(question_id, letter)`, o
                    # INSERT da nova alternativa "A" tentava entrar antes de
                    # a antiga "A" ser apagada -> violação de unicidade em
                    # TODA edição que reenviasse alternativas (ou seja,
                    # praticamente toda edição feita por esta tela).
                    #
                    # A correção é nunca apagar+recriar uma letra que já
                    # existe: atualizamos a alternativa existente em memória
                    # (mesma linha/mesmo id) e só inserimos/removemos as
                    # letras que de fato mudaram de conjunto — nesse caso o
                    # DELETE e o INSERT são de letras diferentes e nunca
                    # colidem na constraint.
                    correct = next(alt for alt in data.alternatives if alt.is_correct)
                    existing_by_letter = {alt.letter: alt for alt in question.alternatives}
                    incoming_letters = {alt.letter for alt in data.alternatives}

                    for letter, existing_alt in list(existing_by_letter.items()):
                        if letter not in incoming_letters:
                            question.alternatives.remove(existing_alt)

                    for alt in data.alternatives:
                        existing_alt = existing_by_letter.get(alt.letter)
                        if existing_alt is not None:
                            existing_alt.text = alt.text
                            existing_alt.is_correct = alt.is_correct
                            existing_alt.image_url = alt.image_url
                        else:
                            question.alternatives.append(
                                QuestionAlternative(
                                    letter=alt.letter,
                                    text=alt.text,
                                    is_correct=alt.is_correct,
                                    image_url=alt.image_url,
                                )
                            )
                    question.correct_alternative_letter = correct.letter

                if new_tags is not None:
                    question.tags = new_tags

                if data.attachments is not None:
                    # Substitui integralmente o conjunto de anexos, mesmo padrão
                    # já adotado para `alternatives` — o cascade
                    # "all, delete-orphan" da relationship cuida de apagar os
                    # antigos que saírem da lista.
                    question.attachments = [
                        QuestionAttachment(
                            type=AttachmentType(att.type), url=att.url, alt_text=att.alt_text
                        )
                        for att in data.attachments
                    ]

                await self._session.flush()
                self._session.add(
                    QuestionRevision(
                        question_id=question.id,
                        changed_by=admin_user_id,
                        change_type=QuestionRevisionType.EDICAO,
                        snapshot=_snapshot(question),
                    )
                )
        except IntegrityError as exc:
            logger.warning(
                "question_update.integrity_error",
                question_id=str(question_id),
                error=repr(exc),
            )
            # Backstop genérico: mesmo com as validações acima, uma corrida
            # (ex.: o registro referenciado foi excluído entre a validação e
            # o commit) ainda pode violar uma constraint no banco. Isso vira
            # um 409 com mensagem legível — nunca mais um 500 sem explicação
            # nenhuma. Não é mais o caminho esperado: o bug mais comum
            # (reordenação INSERT/DELETE nas alternativas) foi corrigido
            # acima, então se este backstop disparar de novo, o motivo real
            # está em `structlog`/logs do servidor (`unhandled_exception`
            # nunca chega a rodar aqui, mas o `repr(exc)` do IntegrityError
            # original ajuda a diagnosticar — considere logar `exc` também).
            raise ConflictError(
                "Não foi possível salvar a questão porque um dos dados enviados "
                "conflita com o que já existe no banco. Recarregue a questão e "
                "tente novamente; se persistir, verifique os logs do servidor."
            ) from exc

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