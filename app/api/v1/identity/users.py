"""Endpoints HTTP de conta, perfil e administração de usuários."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.schemas.identity import (
    AdminUserListItem,
    AvatarPresignRequest,
    ChangePasswordRequest,
    MeResponse,
    UpdateAccountRequest,
    UpdateProfileRequest,
    UpdateUserStatusRequest,
    UserProfileResponse,
    PublicUserProfileResponse,
)
from app.security.dependencies import CurrentAdminUser, CurrentUser
from app.services.identity import UserService
from app.core.config import settings
from app.services.storage.s3_service import create_presigned_upload, create_presigned_download, upload_profile_avatar
from app.models.identity.user import User
from app.models.analytics.ranking import UserRanking
from app.models.platform.comment import Comment

router = APIRouter()


def get_user_service(session: Annotated[AsyncSession, Depends(get_db)]) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.get("/me", response_model=Envelope[MeResponse])
async def get_me(
    current_user: CurrentUser, user_service: UserServiceDep
) -> Envelope[MeResponse]:
    profile = await user_service.get_profile(current_user.id)
    return Envelope(
        data=MeResponse(
            id=current_user.id,
            email=current_user.email,
            full_name=current_user.full_name,
            is_admin=current_user.is_admin,
            is_active=current_user.is_active,
            created_at=current_user.created_at,
            profile=UserProfileResponse.model_validate(profile),
        )
    )


@router.patch("/me", response_model=Envelope[MeResponse])
async def update_me(
    body: UpdateAccountRequest,
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> Envelope[MeResponse]:
    user = await user_service.update_account(current_user, full_name=body.full_name)
    profile = await user_service.get_profile(user.id)
    return Envelope(
        data=MeResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            created_at=user.created_at,
            profile=UserProfileResponse.model_validate(profile),
        )
    )



@router.post("/me/avatar/presign", response_model=Envelope[dict])
async def presign_my_avatar(
    body: AvatarPresignRequest,
    current_user: CurrentUser,
) -> Envelope[dict]:
    """Gera URL presignada para upload da foto de perfil no S3."""
    upload = create_presigned_upload(
        filename=body.filename,
        content_type=body.content_type,
        prefix=settings.S3_PROFILE_PREFIX,
    )
    return Envelope(data=upload)


@router.post("/me/avatar", response_model=Envelope[UserProfileResponse])
async def upload_my_avatar(
    current_user: CurrentUser,
    user_service: UserServiceDep,
    file: UploadFile = File(...),
) -> Envelope[UserProfileResponse]:
    """Recebe o avatar no backend e envia para o S3 sem CORS no navegador."""
    content_type = file.content_type
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=422, detail="Tipo de imagem não permitido.")

    data = await file.read(settings.S3_MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.S3_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="A imagem deve ter no máximo 8 MB.")

    from io import BytesIO

    uploaded = upload_profile_avatar(
        BytesIO(data),
        content_type,
        prefix=settings.S3_PROFILE_PREFIX,
    )
    profile = await user_service.update_profile(
        current_user.id,
        {"avatar_url": uploaded["public_url"]},
    )
    return Envelope(data=UserProfileResponse.model_validate(profile))


@router.get("/{user_id}/avatar")
async def get_user_avatar(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """Redireciona o avatar para uma URL S3 assinada de leitura."""
    result = await session.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user or not user.profile or not user.profile.avatar_url:
        raise HTTPException(status_code=404, detail="Avatar não encontrado.")

    from urllib.parse import unquote, urlparse

    parsed = urlparse(user.profile.avatar_url)
    key = unquote(parsed.path.lstrip("/"))
    if not key:
        raise HTTPException(status_code=404, detail="Avatar não encontrado.")

    return RedirectResponse(
        url=create_presigned_download(key),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.patch("/me/profile", response_model=Envelope[UserProfileResponse])
async def update_my_profile(
    body: UpdateProfileRequest,
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> Envelope[UserProfileResponse]:
    fields = body.model_dump(exclude_unset=True)
    profile = await user_service.update_profile(current_user.id, fields)
    return Envelope(data=UserProfileResponse.model_validate(profile))



@router.get("/{user_id}/public-profile", response_model=Envelope[PublicUserProfileResponse])
async def get_public_profile(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[PublicUserProfileResponse]:
    """Perfil público seguro, usado no ranking e na comunidade."""
    result = await session.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    ranking_result = await session.execute(
        select(UserRanking).where(UserRanking.user_id == user_id)
    )
    ranking = ranking_result.scalar_one_or_none()

    comments_count = await session.scalar(
        select(func.count()).select_from(Comment).where(
            Comment.user_id == user_id,
            Comment.deleted_at.is_(None),
            Comment.status == "publicado",
        )
    ) or 0

    return Envelope(
        data=PublicUserProfileResponse(
            id=user.id,
            full_name=user.full_name,
            created_at=user.created_at,
            profile=UserProfileResponse.model_validate(user.profile),
            ranking={
                "rank": ranking.rank if ranking else None,
                "total_points": ranking.total_points if ranking else 0,
                "questions_answered": ranking.questions_answered if ranking else 0,
                "accuracy": ranking.accuracy if ranking else 0,
                "streak_days": ranking.streak_days if ranking else 0,
            },
            comments_count=comments_count,
        )
    )


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> None:
    await user_service.change_password(
        current_user, current_password=body.current_password, new_password=body.new_password
    )


@router.get("", response_model=Envelope[list[AdminUserListItem]])
async def list_users(
    _admin: CurrentAdminUser,
    user_service: UserServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Envelope[list[AdminUserListItem]]:
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    users = await user_service.list_users(limit=limit, cursor_id=cursor_id)
    next_cursor = CursorPage.encode_cursor(str(users[-1].id)) if len(users) == limit else None

    return Envelope(
        data=[AdminUserListItem.model_validate(u) for u in users],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )


@router.get("/{user_id}", response_model=Envelope[AdminUserListItem])
async def get_user(
    user_id: uuid.UUID,
    _admin: CurrentAdminUser,
    user_service: UserServiceDep,
) -> Envelope[AdminUserListItem]:
    user = await user_service.get_user(user_id)
    return Envelope(data=AdminUserListItem.model_validate(user))


@router.patch("/{user_id}/status", response_model=Envelope[AdminUserListItem])
async def update_user_status(
    user_id: uuid.UUID,
    body: UpdateUserStatusRequest,
    _admin: CurrentAdminUser,
    user_service: UserServiceDep,
) -> Envelope[AdminUserListItem]:
    user = await user_service.set_active_status(user_id, body.is_active)
    return Envelope(data=AdminUserListItem.model_validate(user))