"""Repositório de identidades externas vinculadas a usuários."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity.auth_provider import UserAuthProvider
from app.repositories.base import BaseRepository


class UserAuthProviderRepository(BaseRepository[UserAuthProvider]):
    model = UserAuthProvider

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_provider_subject(
        self, provider: str, provider_subject: str
    ) -> UserAuthProvider | None:
        stmt = select(UserAuthProvider).where(
            UserAuthProvider.provider == provider,
            UserAuthProvider.provider_subject == provider_subject,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_and_provider(
        self, user_id: uuid.UUID, provider: str
    ) -> UserAuthProvider | None:
        stmt = select(UserAuthProvider).where(
            UserAuthProvider.user_id == user_id,
            UserAuthProvider.provider == provider,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
