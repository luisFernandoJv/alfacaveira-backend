"""Regras de negócio de moldes de simulado (`ExamTemplate`): criação a partir
de filtros — ou de uma seleção explícita de questões — e consulta (listagem
visível + detalhe).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationDomainError
from app.database.uow import UnitOfWork
from app.models.assessment.exam_template import ExamTemplate
from app.models.identity.user import User
from app.repositories.assessment.exam_template_repository import ExamTemplateRepository
from app.schemas.assessment.exam_template import ExamTemplateCreateRequest

MAX_SELECTED_QUESTIONS = 100


def _filters_snapshot(data: ExamTemplateCreateRequest) -> dict[str, object]:
    """Snapshot (JSONB) dos filtros — ou da seleção explícita — usados para
    montar o simulado. `exam_attempt_service.start_attempt` lê esse snapshot
    de volta na hora de montar as questões da tentativa.
    """
    return {
        "discipline_id": str(data.discipline_id) if data.discipline_id else None,
        "subject_id": str(data.subject_id) if data.subject_id else None,
        "topic_id": str(data.topic_id) if data.topic_id else None,
        "exam_board_id": str(data.exam_board_id) if data.exam_board_id else None,
        "exam_edition_id": str(data.exam_edition_id) if data.exam_edition_id else None,
        "organization_id": str(data.organization_id) if data.organization_id else None,
        "year": data.year,
        "difficulty": data.difficulty.value if data.difficulty else None,
        "tag_id": str(data.tag_id) if data.tag_id else None,
        # ETAPA (2026-08-15): seleção explícita de questões (Banco de
        # Questões → Selecionar → Criar Simulado). Quando presente,
        # `start_attempt` usa essa lista em vez de sortear pelos filtros
        # acima.
        "question_ids": (
            [str(question_id) for question_id in data.question_ids]
            if data.question_ids
            else None
        ),
    }


class ExamTemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._templates = ExamTemplateRepository(session)

    async def create_template(self, user: User, data: ExamTemplateCreateRequest) -> ExamTemplate:
        if data.is_public and not user.is_admin:
            raise ForbiddenError("Apenas administradores podem criar moldes públicos.")

        # Seleção explícita manda na quantidade — ignora `question_count`
        # enviado (mesmo padrão de "backend é autoridade", só que aqui a
        # autoridade sobre a contagem é a própria seleção do usuário).
        question_count = data.question_count
        if data.question_ids is not None:
            unique_ids = list(dict.fromkeys(data.question_ids))
            if not unique_ids:
                raise ValidationDomainError(
                    "Selecione ao menos uma questão para criar o simulado."
                )
            if len(unique_ids) > MAX_SELECTED_QUESTIONS:
                raise ValidationDomainError(
                    f"Selecione no máximo {MAX_SELECTED_QUESTIONS} questões por simulado."
                )
            question_count = len(unique_ids)

        template = ExamTemplate(
            created_by=user.id,
            title=data.title,
            description=data.description,
            question_count=question_count,
            time_limit_minutes=data.time_limit_minutes,
            filters_snapshot=_filters_snapshot(data),
            is_public=data.is_public,
        )

        async with UnitOfWork(self._session):
            await self._templates.add(template)

        return template

    async def get_template(self, template_id: uuid.UUID, user_id: uuid.UUID) -> ExamTemplate:
        template = await self._templates.get_by_id(template_id)
        # `NotFoundError` também para molde pessoal de outro usuário — não expõe existência.
        if template is None or not (template.is_public or template.created_by == user_id):
            raise NotFoundError("Molde de simulado não encontrado.")
        return template

    async def list_templates(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[ExamTemplate]:
        return await self._templates.list_visible(user_id=user_id, limit=limit, cursor_id=cursor_id)