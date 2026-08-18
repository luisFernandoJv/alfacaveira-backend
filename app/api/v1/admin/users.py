import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.schemas.identity.user import AdminUserListItem
from app.security.dependencies import CurrentAdminUser
from app.services.identity.user_service import UserService
from sqlalchemy import select
from app.models.identity.user import User

router = APIRouter()

@router.get("/users", response_model=Envelope[list[AdminUserListItem]])
async def list_users_admin(
    admin: CurrentAdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> Envelope[list[AdminUserListItem]]:
    user_service = UserService(session)
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    # Nota: UserService.list_users não tem filtro por is_active, vamos adicionar.
    # Por simplicidade, vou usar diretamente o repositório.
    from app.repositories.identity.user_repository import UserRepository
    repo = UserRepository(session)
    
    # Construir query com filtro
    stmt = select(User).order_by(User.created_at.asc(), User.id.asc()).limit(limit)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if cursor_id:
        cursor_user = await repo.get_by_id(cursor_id)
        if cursor_user:
            stmt = stmt.where(
                (User.created_at > cursor_user.created_at) |
                ((User.created_at == cursor_user.created_at) & (User.id > cursor_user.id))
            )
    result = await session.execute(stmt)
    users = list(result.scalars().all())
    next_cursor = CursorPage.encode_cursor(str(users[-1].id)) if len(users) == limit else None
    return Envelope(
        data=[AdminUserListItem.model_validate(u) for u in users],
        meta=Meta(next_cursor=next_cursor, has_more=next_cursor is not None),
    )