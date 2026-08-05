"""Endpoints HTTP de moldes de simulado (`ExamTemplate`).

Qualquer usuário autenticado pode criar um molde pessoal (`is_public=False`);
apenas administradores podem criar moldes públicos — o serviço aplica essa
regra (`ForbiddenError`), não este router.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.schemas.assessment.exam_template import (
    ExamTemplateCreateRequest,
    ExamTemplateDetailResponse,
    ExamTemplateListItem,
)
from app.security.dependencies import CurrentUser
from app.services.assessment.exam_template_service import ExamTemplateService

router = APIRouter()


def get_exam_template_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExamTemplateService:
    return ExamTemplateService(session)


ExamTemplateServiceDep = Annotated[ExamTemplateService, Depends(get_exam_template_service)]


@router.post(
    "", response_model=Envelope[ExamTemplateDetailResponse], status_code=status.HTTP_201_CREATED
)
async def create_exam_template(
    body: ExamTemplateCreateRequest,
    current_user: CurrentUser,
    exam_template_service: ExamTemplateServiceDep,
) -> Envelope[ExamTemplateDetailResponse]:
    template = await exam_template_service.create_template(current_user, body)
    return Envelope(data=ExamTemplateDetailResponse.model_validate(template))


@router.get("", response_model=Envelope[list[ExamTemplateListItem]])
async def list_exam_templates(
    current_user: CurrentUser,
    exam_template_service: ExamTemplateServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Envelope[list[ExamTemplateListItem]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    templates = await exam_template_service.list_templates(
        current_user.id, limit=limit, cursor_id=cursor_id
    )
    next_cursor = (
        CursorPage.encode_cursor(str(templates[-1].id)) if len(templates) == limit else None
    )

    return Envelope(
        data=[ExamTemplateListItem.model_validate(t) for t in templates],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )


@router.get("/{template_id}", response_model=Envelope[ExamTemplateDetailResponse])
async def get_exam_template(
    template_id: uuid.UUID,
    current_user: CurrentUser,
    exam_template_service: ExamTemplateServiceDep,
) -> Envelope[ExamTemplateDetailResponse]:
    template = await exam_template_service.get_template(template_id, current_user.id)
    return Envelope(data=ExamTemplateDetailResponse.model_validate(template))
