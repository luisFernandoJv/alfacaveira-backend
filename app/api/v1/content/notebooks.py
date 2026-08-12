# app/api/v1/content/notebooks.py
"""Endpoints HTTP de cadernos (notebooks)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.models.enums import FeatureKey
from app.schemas.content.notebook import (
    NotebookAddQuestionRequest,
    NotebookCreateRequest,
    NotebookFolderResponse,
    NotebookListResponse,
    NotebookQuestionResponse,
    NotebookResponse,
    NotebookTagResponse,
    NotebookUpdateRequest,
)
from app.security.dependencies import CurrentUser, RequireFeature
from app.services.content.notebook_service import NotebookService

router = APIRouter()


def get_notebook_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotebookService:
    return NotebookService(session)


NotebookServiceDep = Annotated[NotebookService, Depends(get_notebook_service)]


# ==================================================================== #
# CADERNOS
# ==================================================================== #


@router.get("", response_model=Envelope[NotebookListResponse])
async def list_notebooks(
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    folder_id: Annotated[uuid.UUID | None, Query()] = None,
    is_favorite: Annotated[bool | None, Query()] = None,
    tag_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Envelope[NotebookListResponse]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    notebooks = await notebook_service.list_notebooks(
        user_id=current_user.id,
        limit=limit,
        cursor_id=cursor_id,
        folder_id=folder_id,
        is_favorite=is_favorite,
        tag_id=tag_id,
        search=search,
    )

    total = await notebook_service._notebooks.count_by_user(current_user.id)

    next_cursor = (
        CursorPage.encode_cursor(str(notebooks[-1].id)) if len(notebooks) == limit else None
    )

    # Calcular question_count para cada notebook
    for notebook in notebooks:
        notebook.question_count = len(notebook.questions)

    return Envelope(
        data=NotebookListResponse(
            items=[NotebookResponse.model_validate(n) for n in notebooks],
            total=total,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )
    )


@router.get("/{notebook_id}", response_model=Envelope[NotebookResponse])
async def get_notebook(
    notebook_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookResponse]:
    notebook = await notebook_service.get_notebook(notebook_id, current_user.id)
    notebook.question_count = len(notebook.questions)
    return Envelope(data=NotebookResponse.model_validate(notebook))


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
    notebook = await notebook_service.create_notebook(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        folder_id=body.folder_id,
        tag_ids=body.tag_ids,
    )
    notebook.question_count = len(notebook.questions)
    return Envelope(data=NotebookResponse.model_validate(notebook))


@router.put("/{notebook_id}", response_model=Envelope[NotebookResponse])
async def update_notebook(
    notebook_id: uuid.UUID,
    body: NotebookUpdateRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookResponse]:
    notebook = await notebook_service.update_notebook(
        notebook_id=notebook_id,
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        is_favorite=body.is_favorite,
        folder_id=body.folder_id,
        tag_ids=body.tag_ids,
    )
    notebook.question_count = len(notebook.questions)
    return Envelope(data=NotebookResponse.model_validate(notebook))


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notebook(
    notebook_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> None:
    await notebook_service.delete_notebook(notebook_id, current_user.id)


# ==================================================================== #
# QUESTÕES NO CADERNO
# ==================================================================== #


@router.post(
    "/{notebook_id}/questions",
    response_model=Envelope[NotebookQuestionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_question_to_notebook(
    notebook_id: uuid.UUID,
    body: NotebookAddQuestionRequest,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookQuestionResponse]:
    notebook_question = await notebook_service.add_question_to_notebook(
        notebook_id=notebook_id,
        user_id=current_user.id,
        question_id=body.question_id,
        note=body.note,
    )
    return Envelope(data=NotebookQuestionResponse.model_validate(notebook_question))


@router.delete("/{notebook_id}/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_question_from_notebook(
    notebook_id: uuid.UUID,
    question_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> None:
    await notebook_service.remove_question_from_notebook(
        notebook_id=notebook_id,
        user_id=current_user.id,
        question_id=question_id,
    )


# ==================================================================== #
# PASTAS
# ==================================================================== #


@router.get("/folders", response_model=Envelope[list[NotebookFolderResponse]])
async def list_folders(
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[list[NotebookFolderResponse]]:
    folders = await notebook_service.get_folders(current_user.id)
    return Envelope(data=[NotebookFolderResponse.model_validate(f) for f in folders])


@router.post(
    "/folders",
    response_model=Envelope[NotebookFolderResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    body: dict,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookFolderResponse]:
    name = body.get("name")
    parent_id = body.get("parent_id")

    if not name:
        raise ValueError("O campo 'name' é obrigatório.")

    folder = await notebook_service.create_folder(
        user_id=current_user.id,
        name=name,
        parent_id=parent_id,
    )
    return Envelope(data=NotebookFolderResponse.model_validate(folder))


@router.put("/folders/{folder_id}", response_model=Envelope[NotebookFolderResponse])
async def update_folder(
    folder_id: uuid.UUID,
    body: dict,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookFolderResponse]:
    name = body.get("name")

    if not name:
        raise ValueError("O campo 'name' é obrigatório.")

    folder = await notebook_service.update_folder(
        folder_id=folder_id,
        user_id=current_user.id,
        name=name,
    )
    return Envelope(data=NotebookFolderResponse.model_validate(folder))


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
    move_notebooks_to_parent: bool = True,
) -> None:
    await notebook_service.delete_folder(
        folder_id=folder_id,
        user_id=current_user.id,
        move_notebooks_to_parent=move_notebooks_to_parent,
    )


# ==================================================================== #
# TAGS
# ==================================================================== #


@router.get("/tags", response_model=Envelope[list[NotebookTagResponse]])
async def list_tags(
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[list[NotebookTagResponse]]:
    tags = await notebook_service.get_tags(current_user.id)
    return Envelope(data=[NotebookTagResponse.model_validate(t) for t in tags])


@router.post(
    "/tags",
    response_model=Envelope[NotebookTagResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_tag(
    body: dict,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> Envelope[NotebookTagResponse]:
    name = body.get("name")

    if not name:
        raise ValueError("O campo 'name' é obrigatório.")

    tag = await notebook_service.create_tag(
        user_id=current_user.id,
        name=name,
    )
    return Envelope(data=NotebookTagResponse.model_validate(tag))


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: uuid.UUID,
    current_user: CurrentUser,
    notebook_service: NotebookServiceDep,
) -> None:
    await notebook_service.delete_tag(tag_id, current_user.id)