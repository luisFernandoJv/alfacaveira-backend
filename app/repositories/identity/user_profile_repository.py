"""Repositório de acesso a dados de `UserProfile`."""

import uuid

from sqlalchemy import select

from app.models.identity.user import UserProfile
from app.repositories.base import BaseRepository


class UserProfileRepository(BaseRepository[UserProfile]):
    model = UserProfile

    async def get_by_user_id(self, user_id: uuid.UUID) -> UserProfile | None:
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
