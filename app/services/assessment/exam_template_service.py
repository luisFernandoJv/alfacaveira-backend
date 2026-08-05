"""Regras de negócio de moldes de simulado (`ExamTemplate`): criação a partir
de filtros e consulta (listagem visível + detalhe).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.assessment.exam_template import ExamTemplate
from app.models.identity.user import User
from app.repositories.assessment.exam_template_repository import ExamTemplateRepository
from app.schemas.assessment.exam_template import ExamTemplateCreateRequest


def _filters_snapshot(data: ExamTemplateCreateRequest) -> dict[str, object]:
    """Snapshot (JSONB) dos filtros usados para montar o simulado."""
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
    }


class ExamTemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._templates = ExamTemplateRepository(session)

    async def create_template(self, user: User, data: ExamTemplateCreateRequest) -> ExamTemplate:
        if data.is_public and not user.is_admin:
            raise ForbiddenError("Apenas administradores podem criar moldes públicos.")

        template = ExamTemplate(
            created_by=user.id,
            title=data.title,
            description=data.description,
            question_count=data.question_count,
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
