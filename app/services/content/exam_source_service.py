"""Regras de negócio de banca examinadora, órgão e edição de concurso."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content.exam_source import ExamBoard, ExamEdition, Organization
from app.repositories.content.exam_source_repository import (
    ExamBoardRepository,
    ExamEditionRepository,
    OrganizationRepository,
)


class ExamSourceService:
    def __init__(self, session: AsyncSession) -> None:
        self._exam_boards = ExamBoardRepository(session)
        self._organizations = OrganizationRepository(session)
        self._exam_editions = ExamEditionRepository(session)

    async def list_exam_boards(self) -> list[ExamBoard]:
        return await self._exam_boards.list_all()

    async def list_organizations(self) -> list[Organization]:
        return await self._organizations.list_all()

    async def list_exam_editions(
        self,
        organization_id: uuid.UUID | None = None,
        exam_board_id: uuid.UUID | None = None,
    ) -> list[ExamEdition]:
        return await self._exam_editions.list_filtered(
            organization_id=organization_id, exam_board_id=exam_board_id
        )
