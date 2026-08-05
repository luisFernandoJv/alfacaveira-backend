"""Endpoints públicos de banca examinadora, órgão e edição de concurso."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.content import ExamBoardResponse, ExamEditionResponse, OrganizationResponse
from app.services.content import ExamSourceService

router = APIRouter()


def get_exam_source_service(session: Annotated[AsyncSession, Depends(get_db)]) -> ExamSourceService:
    return ExamSourceService(session)


ExamSourceServiceDep = Annotated[ExamSourceService, Depends(get_exam_source_service)]


@router.get("/exam-boards", response_model=Envelope[list[ExamBoardResponse]])
async def list_exam_boards(
    exam_source_service: ExamSourceServiceDep,
) -> Envelope[list[ExamBoardResponse]]:
    boards = await exam_source_service.list_exam_boards()
    return Envelope(data=[ExamBoardResponse.model_validate(b) for b in boards])


@router.get("/organizations", response_model=Envelope[list[OrganizationResponse]])
async def list_organizations(
    exam_source_service: ExamSourceServiceDep,
) -> Envelope[list[OrganizationResponse]]:
    organizations = await exam_source_service.list_organizations()
    return Envelope(data=[OrganizationResponse.model_validate(o) for o in organizations])


@router.get("/exam-editions", response_model=Envelope[list[ExamEditionResponse]])
async def list_exam_editions(
    exam_source_service: ExamSourceServiceDep,
    organization_id: Annotated[uuid.UUID | None, Query()] = None,
    exam_board_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Envelope[list[ExamEditionResponse]]:
    editions = await exam_source_service.list_exam_editions(
        organization_id=organization_id, exam_board_id=exam_board_id
    )
    return Envelope(data=[ExamEditionResponse.model_validate(e) for e in editions])
