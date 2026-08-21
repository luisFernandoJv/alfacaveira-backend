"""Endpoints HTTP de questões.

Listagem e detalhe são públicos (qualquer usuário autenticado); CRUD é
restrito a administradores (`CurrentAdminUser`) — não existe papel
"editor" separado no modelo de usuário atual.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


from app.schemas.platform.question_report import QuestionReportCreateRequest, QuestionReportResponse
from app.services.platform.question_report_service import QuestionReportService
from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.models.enums import QuestionAnswerStatus, QuestionDifficulty, QuestionStatus
from app.repositories.content.question_repository import QuestionFilters
from app.schemas.content.question import (
    QuestionCreateRequest,
    QuestionDetailResponse,
    QuestionFacetsResponse,
    QuestionListItem,
    QuestionStatusUpdateRequest,
    QuestionUpdateRequest,
)
from app.security.dependencies import CurrentAdminUser, CurrentUser
from app.services.content.question_service import QuestionService
from app.services.storage.s3_service import create_presigned_upload

router = APIRouter()


def get_question_service(session: Annotated[AsyncSession, Depends(get_db)]) -> QuestionService:
    return QuestionService(session)


QuestionServiceDep = Annotated[QuestionService, Depends(get_question_service)]


@router.get("", response_model=Envelope[list[QuestionListItem]])
async def list_questions(
    current_user: CurrentUser,
    question_service: QuestionServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    discipline_id: Annotated[uuid.UUID | None, Query()] = None,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
    topic_id: Annotated[uuid.UUID | None, Query()] = None,
    exam_board_id: Annotated[uuid.UUID | None, Query()] = None,
    exam_edition_id: Annotated[uuid.UUID | None, Query()] = None,
    organization_id: Annotated[uuid.UUID | None, Query()] = None,
    year: Annotated[int | None, Query()] = None,
    difficulty: Annotated[QuestionDifficulty | None, Query()] = None,
    tag_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    question_status: Annotated[
        QuestionStatus | None, Query(alias="status")
    ] = QuestionStatus.PUBLICADA,
    answer_status: Annotated[
        QuestionAnswerStatus | None,
        Query(description="Filtra pelo status de resposta do usuário autenticado."),
    ] = None,
    favorite_only: Annotated[
        bool | None,
        Query(description="Se true, retorna somente questões favoritadas pelo usuário autenticado."),
    ] = None,
) -> Envelope[list[QuestionListItem]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    filters = QuestionFilters(
        discipline_id=discipline_id,
        subject_id=subject_id,
        topic_id=topic_id,
        exam_board_id=exam_board_id,
        exam_edition_id=exam_edition_id,
        organization_id=organization_id,
        year=year,
        difficulty=difficulty,
        status=question_status,
        tag_id=tag_id,
        search=search,
        answer_status=answer_status,
        favorite_only=favorite_only,
    )
    questions = await question_service.list_questions(
        limit=limit, cursor_id=cursor_id, filters=filters, user_id=current_user.id
    )
    # Contagem total filtrada (sem paginar), para o contador em tempo real
    # do Banco de Questões ("N questões encontradas"). Sequencial de
    # propósito — mesma `AsyncSession`, que não é concorrente (ver
    # `QuestionService._session_gather`).
    total = await question_service.count_questions(filters=filters, user_id=current_user.id)
    next_cursor = (
        CursorPage.encode_cursor(str(questions[-1].id)) if len(questions) == limit else None
    )

    return Envelope(
        data=[QuestionListItem.model_validate(q) for q in questions],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None, total=total),
    )


@router.get("/facets", response_model=Envelope[QuestionFacetsResponse])
async def get_question_facets(
    current_user: CurrentUser,
    question_service: QuestionServiceDep,
    discipline_id: Annotated[uuid.UUID | None, Query()] = None,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
    topic_id: Annotated[uuid.UUID | None, Query()] = None,
    exam_board_id: Annotated[uuid.UUID | None, Query()] = None,
    exam_edition_id: Annotated[uuid.UUID | None, Query()] = None,
    organization_id: Annotated[uuid.UUID | None, Query()] = None,
    year: Annotated[int | None, Query()] = None,
    difficulty: Annotated[QuestionDifficulty | None, Query()] = None,
    tag_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    question_status: Annotated[
        QuestionStatus | None, Query(alias="status")
    ] = QuestionStatus.PUBLICADA,
    answer_status: Annotated[
        QuestionAnswerStatus | None,
        Query(description="Filtra pelo status de resposta do usuário autenticado."),
    ] = None,
    favorite_only: Annotated[
        bool | None,
        Query(description="Se true, calcula facetas só sobre questões favoritadas."),
    ] = None,
) -> Envelope[QuestionFacetsResponse]:
    """Contagem por opção de cada dimensão de filtro, dentro do universo já
    filtrado — alimenta os números ao lado de cada opção no painel de
    filtros do Explorer (`filters-panel.tsx` / `use-questions-api.ts`).

    Aceita exatamente os mesmos filtros de `GET /questions` (exceto
    paginação/ordenação, que não fazem sentido para uma agregação). Rota
    declarada ANTES de `/{question_id}` de propósito — caso contrário
    `"facets"` seria capturado como um `question_id` inválido.
    """
    filters = QuestionFilters(
        discipline_id=discipline_id,
        subject_id=subject_id,
        topic_id=topic_id,
        exam_board_id=exam_board_id,
        exam_edition_id=exam_edition_id,
        organization_id=organization_id,
        year=year,
        difficulty=difficulty,
        status=question_status,
        tag_id=tag_id,
        search=search,
        answer_status=answer_status,
        favorite_only=favorite_only,
    )
    facets = await question_service.get_facets(filters=filters, user_id=current_user.id)
    return Envelope(data=QuestionFacetsResponse.model_validate(facets))


class AttachmentPresignRequest(BaseModel):
    filename: str
    content_type: str


class AttachmentPresignResponse(BaseModel):
    upload_url: str
    public_url: str
    expires_in: int


@router.post(
    "/attachments/presign",
    response_model=Envelope[AttachmentPresignResponse],
)
async def presign_attachment_upload(
    body: AttachmentPresignRequest,
    _admin: CurrentAdminUser,
) -> Envelope[AttachmentPresignResponse]:
    """Gera uma URL assinada (PUT) para o admin subir uma imagem direto pro
    S3, sem passar o binário pela API. Declarada ANTES de `/{question_id}`
    de propósito (mesmo motivo de `/facets`): `"attachments"` não pode ser
    capturado como um `question_id` inválido.

    Fluxo completo em 3 passos, ver README/`docs` de imagens: (1) o
    frontend chama esta rota com `filename` + `content_type`; (2) faz um
    `PUT` direto pro `upload_url` retornado, com o arquivo no corpo; (3)
    guarda `public_url` no formulário e envia junto com
    `POST/PATCH /questions` (campo `attachments`).
    """
    result = create_presigned_upload(filename=body.filename, content_type=body.content_type)
    return Envelope(
        data=AttachmentPresignResponse(
            upload_url=result["upload_url"],
            public_url=result["public_url"],
            expires_in=result["expires_in"],
        )
    )


@router.get("/{question_id}", response_model=Envelope[QuestionDetailResponse])
async def get_question(
    question_id: uuid.UUID,
    _current_user: CurrentUser,
    question_service: QuestionServiceDep,
) -> Envelope[QuestionDetailResponse]:
    question = await question_service.get_question(question_id)
    return Envelope(data=QuestionDetailResponse.model_validate(question))


@router.post(
    "", response_model=Envelope[QuestionDetailResponse], status_code=status.HTTP_201_CREATED
)
async def create_question(
    body: QuestionCreateRequest,
    admin: CurrentAdminUser,
    question_service: QuestionServiceDep,
) -> Envelope[QuestionDetailResponse]:
    question = await question_service.create_question(admin.id, body)
    return Envelope(data=QuestionDetailResponse.model_validate(question))


@router.patch("/{question_id}", response_model=Envelope[QuestionDetailResponse])
async def update_question(
    question_id: uuid.UUID,
    body: QuestionUpdateRequest,
    admin: CurrentAdminUser,
    question_service: QuestionServiceDep,
) -> Envelope[QuestionDetailResponse]:
    question = await question_service.update_question(question_id, admin.id, body)
    return Envelope(data=QuestionDetailResponse.model_validate(question))


@router.patch("/{question_id}/status", response_model=Envelope[QuestionDetailResponse])
async def update_question_status(
    question_id: uuid.UUID,
    body: QuestionStatusUpdateRequest,
    admin: CurrentAdminUser,
    question_service: QuestionServiceDep,
) -> Envelope[QuestionDetailResponse]:
    question = await question_service.update_status(question_id, admin.id, body.status)
    return Envelope(data=QuestionDetailResponse.model_validate(question))


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: uuid.UUID,
    admin: CurrentAdminUser,
    question_service: QuestionServiceDep,
) -> None:
    await question_service.delete_question(question_id, admin.id)


@router.post(
    "/{question_id}/report",
    response_model=Envelope[QuestionReportResponse],
    status_code=status.HTTP_201_CREATED,
)
async def report_question(
    question_id: uuid.UUID,
    body: QuestionReportCreateRequest,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[QuestionReportResponse]:
    """Reporta um problema em uma questão."""
    service = QuestionReportService(session)
    report = await service.create_report(current_user.id, question_id, body)
    return Envelope(data=QuestionReportResponse.model_validate(report))