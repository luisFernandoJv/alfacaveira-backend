"""Repositório de acesso a dados de `ExamTemplate`.

Listagem sempre restrita aos moldes *visíveis* ao usuário: os públicos
(`is_public=True`, tipicamente criados por administradores) mais os
próprios (`created_by=user_id`) — mesmo padrão de listagem pessoal usado em
`TrainingSessionRepository`, mas com a exceção do escopo público.
"""

import uuid

from sqlalchemy import or_, select

from app.models.assessment.exam_template import ExamTemplate
from app.repositories.base import BaseRepository


class ExamTemplateRepository(BaseRepository[ExamTemplate]):
    model = ExamTemplate

    async def list_visible(
        self, user_id: uuid.UUID, limit: int, cursor_id: uuid.UUID | None
    ) -> list[ExamTemplate]:
        """Moldes públicos + próprios do usuário, mais recentes primeiro."""
        stmt = (
            select(ExamTemplate)
            .where(or_(ExamTemplate.is_public.is_(True), ExamTemplate.created_by == user_id))
            .order_by(ExamTemplate.created_at.desc(), ExamTemplate.id.desc())
            .limit(limit)
        )

        if cursor_id is not None:
            cursor_template = await self.get_by_id(cursor_id)
            if cursor_template is not None:
                stmt = stmt.where(
                    (ExamTemplate.created_at < cursor_template.created_at)
                    | (
                        (ExamTemplate.created_at == cursor_template.created_at)
                        & (ExamTemplate.id < cursor_template.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())
