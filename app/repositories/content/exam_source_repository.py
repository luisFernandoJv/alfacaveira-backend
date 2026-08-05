"""Repositórios de acesso a dados de banca, órgão e edição de concurso."""

import uuid

from sqlalchemy import select

from app.models.content.exam_source import ExamBoard, ExamEdition, Organization
from app.repositories.base import BaseRepository


class ExamBoardRepository(BaseRepository[ExamBoard]):
    model = ExamBoard

    async def list_all(self) -> list[ExamBoard]:
        stmt = select(ExamBoard).order_by(ExamBoard.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization

    async def list_all(self) -> list[Organization]:
        stmt = select(Organization).order_by(Organization.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ExamEditionRepository(BaseRepository[ExamEdition]):
    model = ExamEdition

    async def list_filtered(
        self,
        organization_id: uuid.UUID | None = None,
        exam_board_id: uuid.UUID | None = None,
    ) -> list[ExamEdition]:
        stmt = select(ExamEdition).order_by(ExamEdition.year.desc(), ExamEdition.name.asc())
        if organization_id is not None:
            stmt = stmt.where(ExamEdition.organization_id == organization_id)
        if exam_board_id is not None:
            stmt = stmt.where(ExamEdition.exam_board_id == exam_board_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
