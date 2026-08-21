# app/api/v1/learning/notebooks.py
"""Endpoints HTTP de cadernos."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.models.enums import FeatureKey
from app.schemas.learning.notebook import (
    NotebookCreateRequest,
    NotebookDetailResponse,
    NotebookFavoriteToggleRequest,
    NotebookListResponse,
    NotebookResponse,
    NotebookUpdateRequest,
)
from app.schemas.learning.notebook_folder import (
    NotebookFolderCreateRequest,
    NotebookFolderListResponse,
    NotebookFolderResponse,
    NotebookFolderUpdateRequest,
)
from app.schemas.learning.notebook_question import (
    NotebookQuestionAddRequest,
    NotebookQuestionBulkAddRequest,
    NotebookQuestionCopyRequest,
    NotebookQuestionListResponse,
    NotebookQuestionMoveRequest,
    NotebookQuestionResponse,
)
from app.schemas.learning.notebook_tag import (
    NotebookTagCreateRequest,
    NotebookTagListResponse,
    NotebookTagResponse,
)
from app.security.dependencies import CurrentUser, RequireFeature
from app.services.learning.notebook_service import NotebookService

router = APIRouter()


def get_notebook_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotebookService:
    return NotebookService(session)


NotebookServiceDep = Annotated[NotebookService, Depends(get_notebook_service)]


# ==================================================================== #
# FOLDERS                                                             #
# ==================================================================== #


@router.get("/folders", response_model=Envelope[NotebookFolderListResponse])
async def list_folders(
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookFolderListResponse]:
    """Lista todas as pastas do usuário."""
    folders = await notebook_service.list_folders(current_user.id)
    return Envelope(
        data=NotebookFolderListResponse(
            items=[NotebookFolderResponse.model_validate(f) for f in folders],
            total=len(folders),
        )
    )


@router.post(
    "/folders",
    response_model=Envelope[NotebookFolderResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    body: NotebookFolderCreateRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookFolderResponse]:
    """Cria uma nova pasta."""
    folder = await notebook_service.create_folder(
        user_id=current_user.id,
        name=body.name,
        parent_id=body.parent_id,
    )
    return Envelope(data=NotebookFolderResponse.model_validate(folder))


@router.patch("/folders/{folder_id}", response_model=Envelope[NotebookFolderResponse])
async def update_folder(
    folder_id: uuid.UUID,
    body: NotebookFolderUpdateRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookFolderResponse]:
    """Renomeia uma pasta."""
    folder = await notebook_service.update_folder(
        folder_id=folder_id,
        user_id=current_user.id,
        name=body.name,
    )
    return Envelope(data=NotebookFolderResponse.model_validate(folder))


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> None:
    """Exclui uma pasta (move cadernos para root)."""
    await notebook_service.delete_folder(folder_id, current_user.id)


# ==================================================================== #
# TAGS                                                                #
# ==================================================================== #


@router.get("/tags", response_model=Envelope[NotebookTagListResponse])
async def list_tags(
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookTagListResponse]:
    """Lista todas as tags disponíveis."""
    tags = await notebook_service.list_tags()
    return Envelope(
        data=NotebookTagListResponse(
            items=[NotebookTagResponse.model_validate(t) for t in tags],
            total=len(tags),
        )
    )


@router.post(
    "/tags",
    response_model=Envelope[NotebookTagResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_tag(
    body: NotebookTagCreateRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookTagResponse]:
    """Cria uma nova tag."""
    tag = await notebook_service.create_tag(name=body.name)
    return Envelope(data=NotebookTagResponse.model_validate(tag))


# ==================================================================== #
# NOTEBOOKS                                                           #
# ==================================================================== #


@router.get("", response_model=Envelope[NotebookListResponse])
async def list_notebooks(
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    folder_id: Annotated[uuid.UUID | None, Query()] = None,
    favorite: Annotated[bool | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Envelope[NotebookListResponse]:
    """Lista cadernos do usuário com filtros."""
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    notebooks, total = await notebook_service.list_notebooks(
        user_id=current_user.id,
        limit=limit,
        cursor_id=cursor_id,
        folder_id=folder_id,
        favorite=favorite,
        search=search,
    )

    next_cursor = (
        CursorPage.encode_cursor(str(notebooks[-1].id))
        if len(notebooks) == limit and notebooks
        else None
    )

    return Envelope(
        data=NotebookListResponse(
            items=[NotebookResponse.model_validate(n) for n in notebooks],
            total=total,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )
    )


@router.post(
    "",
    response_model=Envelope[NotebookResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireFeature(FeatureKey.NOTEBOOKS))],
)
async def create_notebook(
    body: NotebookCreateRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookResponse]:
    """Cria um novo caderno."""
    notebook = await notebook_service.create_notebook(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        folder_id=body.folder_id,
        tag_ids=body.tag_ids,
    )

    # Construção manual para evitar MissingGreenlet
    response_data = NotebookResponse(
        id=notebook.id,
        user_id=notebook.user_id,
        name=notebook.name,
        description=notebook.description,
        folder_id=notebook.folder_id,
        folder=NotebookFolderResponse.model_validate(notebook.folder) if notebook.folder else None,
        is_favorite=notebook.is_favorite,
        created_at=notebook.created_at,
        updated_at=notebook.updated_at,
        question_count=0,
    )

    return Envelope(data=response_data)


@router.get("/{notebook_id}", response_model=Envelope[NotebookDetailResponse])
async def get_notebook(
    notebook_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookDetailResponse]:
    """Detalhe de um caderno."""
    notebook = await notebook_service.get_notebook(notebook_id, current_user.id)

    # Extrair questões
    questions = []
    for nq in notebook.questions:
        if nq.question:
            questions.append(nq.question)

    response = NotebookDetailResponse(
        id=notebook.id,
        user_id=notebook.user_id,
        name=notebook.name,
        description=notebook.description,
        folder_id=notebook.folder_id,
        folder=NotebookFolderResponse.model_validate(notebook.folder) if notebook.folder else None,
        is_favorite=notebook.is_favorite,
        created_at=notebook.created_at,
        updated_at=notebook.updated_at,
        question_count=len(questions),
        questions=[
            NotebookQuestionResponse.model_validate(nq)
            for nq in notebook.questions
        ],
    )

    return Envelope(data=response)


@router.patch("/{notebook_id}", response_model=Envelope[NotebookResponse])
async def update_notebook(
    notebook_id: uuid.UUID,
    body: NotebookUpdateRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookResponse]:
    """Atualiza um caderno."""
    notebook = await notebook_service.update_notebook(
        notebook_id=notebook_id,
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        folder_id=body.folder_id,
        is_favorite=body.is_favorite,
        tag_ids=body.tag_ids,
    )

    # Construção manual para evitar MissingGreenlet
    response_data = NotebookResponse(
        id=notebook.id,
        user_id=notebook.user_id,
        name=notebook.name,
        description=notebook.description,
        folder_id=notebook.folder_id,
        folder=NotebookFolderResponse.model_validate(notebook.folder) if notebook.folder else None,
        is_favorite=notebook.is_favorite,
        created_at=notebook.created_at,
        updated_at=notebook.updated_at,
        question_count=getattr(notebook, "_question_count", 0),
    )

    return Envelope(data=response_data)


@router.patch("/{notebook_id}/favorite", response_model=Envelope[NotebookResponse])
async def toggle_favorite(
    notebook_id: uuid.UUID,
    body: NotebookFavoriteToggleRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookResponse]:
    """Alterna o estado de favorito de um caderno."""
    notebook = await notebook_service.update_notebook(
        notebook_id=notebook_id,
        user_id=current_user.id,
        is_favorite=body.is_favorite,
    )

    notebook._question_count = await notebook_service._notebooks.count_questions(notebook_id)

    return Envelope(data=NotebookResponse.model_validate(notebook))


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notebook(
    notebook_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> None:
    """Exclui um caderno (remove as relações com questões)."""
    await notebook_service.delete_notebook(notebook_id, current_user.id)


# ==================================================================== #
# QUESTIONS IN NOTEBOOK                                                #
# ==================================================================== #


@router.get("/{notebook_id}/questions", response_model=Envelope[NotebookQuestionListResponse])
async def list_notebook_questions(
    notebook_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Envelope[NotebookQuestionListResponse]:
    """Lista questões de um caderno."""
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    questions, total = await notebook_service.list_notebook_questions(
        notebook_id=notebook_id,
        user_id=current_user.id,
        limit=limit,
        cursor_id=cursor_id,
        search=search,
    )

    next_cursor = (
        CursorPage.encode_cursor(str(questions[-1].id))
        if len(questions) == limit and questions
        else None
    )

    return Envelope(
        data=NotebookQuestionListResponse(
            items=[NotebookQuestionResponse.model_validate(q) for q in questions],
            total=total,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )
    )


@router.post(
    "/{notebook_id}/questions",
    response_model=Envelope[NotebookQuestionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_question_to_notebook(
    notebook_id: uuid.UUID,
    body: NotebookQuestionAddRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookQuestionResponse]:
    """Adiciona uma questão ao caderno."""
    notebook_question = await notebook_service.add_question(
        notebook_id=notebook_id,
        user_id=current_user.id,
        question_id=body.question_id,
    )
    return Envelope(data=NotebookQuestionResponse.model_validate(notebook_question))


@router.post(
    "/{notebook_id}/questions/bulk",
    response_model=Envelope[list[NotebookQuestionResponse]],
    status_code=status.HTTP_201_CREATED,
)
async def add_questions_to_notebook(
    notebook_id: uuid.UUID,
    body: NotebookQuestionBulkAddRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[list[NotebookQuestionResponse]]:
    """Adiciona múltiplas questões ao caderno."""
    notebook_questions = await notebook_service.add_questions_bulk(
        notebook_id=notebook_id,
        user_id=current_user.id,
        question_ids=body.question_ids,
    )
    return Envelope(data=[NotebookQuestionResponse.model_validate(q) for q in notebook_questions])


@router.delete(
    "/{notebook_id}/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_question_from_notebook(
    notebook_id: uuid.UUID,
    question_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> None:
    """Remove uma questão do caderno."""
    await notebook_service.remove_question(
        notebook_id=notebook_id,
        user_id=current_user.id,
        question_id=question_id,
    )


@router.post("/{notebook_id}/questions/move", response_model=Envelope[list[NotebookQuestionResponse]])
async def move_questions(
    notebook_id: uuid.UUID,
    body: NotebookQuestionMoveRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[list[NotebookQuestionResponse]]:
    """Move questões para outro caderno."""
    result = await notebook_service.move_questions(
        source_notebook_id=notebook_id,
        target_notebook_id=body.target_notebook_id,
        user_id=current_user.id,
        question_ids=body.question_ids,
    )
    return Envelope(data=[NotebookQuestionResponse.model_validate(q) for q in result])


@router.post("/{notebook_id}/questions/copy", response_model=Envelope[list[NotebookQuestionResponse]])
async def copy_questions(
    notebook_id: uuid.UUID,
    body: NotebookQuestionCopyRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[list[NotebookQuestionResponse]]:
    """Copia questões para outro caderno."""
    result = await notebook_service.copy_questions(
        source_notebook_id=notebook_id,
        target_notebook_id=body.target_notebook_id,
        user_id=current_user.id,
        question_ids=body.question_ids,
    )
    return Envelope(data=[NotebookQuestionResponse.model_validate(q) for q in result])