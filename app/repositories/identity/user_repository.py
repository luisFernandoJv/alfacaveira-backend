"""Repositório de acesso a dados de `User`."""

import uuid

from sqlalchemy import select

from app.models.identity.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(self, limit: int, cursor_id: uuid.UUID | None) -> list[User]:
        """Listagem paginada por keyset (created_at, id), estável e sem OFFSET.

        `cursor_id` é o id do último usuário da página anterior; usamos seu
        `created_at` como ponto de corte, com `id` como desempate para linhas
        com o mesmo `created_at`.
        """
        stmt = select(User).order_by(User.created_at.asc(), User.id.asc()).limit(limit)

        if cursor_id is not None:
            cursor_user = await self.get_by_id(cursor_id)
            if cursor_user is not None:
                stmt = stmt.where(
                    (User.created_at > cursor_user.created_at)
                    | (
                        (User.created_at == cursor_user.created_at)
                        & (User.id > cursor_user.id)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
