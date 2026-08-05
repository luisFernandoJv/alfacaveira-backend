"""Regras de negócio de conta, perfil e administração de usuários."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnauthorizedError
from app.database.uow import UnitOfWork
from app.models.identity.user import User, UserProfile
from app.repositories.identity.user_profile_repository import UserProfileRepository
from app.repositories.identity.user_repository import UserRepository
from app.security.password import hash_password, verify_password


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._profiles = UserProfileRepository(session)

    async def get_profile(self, user_id: uuid.UUID) -> UserProfile:
        profile = await self._profiles.get_by_user_id(user_id)
        if profile is None:
            # Contas criadas antes da Etapa 6 (ou por outro fluxo) podem não
            # ter perfil ainda: cria um vazio de forma preguiçosa (upsert).
            profile = UserProfile(user_id=user_id)
            async with UnitOfWork(self._session):
                await self._profiles.add(profile)
        return profile

    async def update_account(self, user: User, full_name: str | None) -> User:
        async with UnitOfWork(self._session):
            if full_name is not None:
                user.full_name = full_name
        return user

    async def update_profile(self, user_id: uuid.UUID, fields: dict[str, object]) -> UserProfile:
        profile = await self.get_profile(user_id)
        async with UnitOfWork(self._session):
            for field, value in fields.items():
                setattr(profile, field, value)
        return profile

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise UnauthorizedError("Senha atual incorreta.")
        async with UnitOfWork(self._session):
            user.password_hash = hash_password(new_password)

    async def list_users(self, limit: int, cursor_id: uuid.UUID | None) -> list[User]:
        return await self._users.list_paginated(limit=limit, cursor_id=cursor_id)

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("Usuário não encontrado.")
        return user

    async def set_active_status(self, user_id: uuid.UUID, is_active: bool) -> User:
        user = await self.get_user(user_id)
        async with UnitOfWork(self._session):
            user.is_active = is_active
        return user
