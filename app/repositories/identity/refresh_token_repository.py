"""Repositório de acesso a dados de `RefreshToken`."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.identity.refresh_token import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(
        self, refresh_token: RefreshToken, replaced_by_token_id: uuid.UUID | None = None
    ) -> None:
        """Marca o token como revogado (usado em rotação e em logout)."""
        refresh_token.revoked_at = datetime.now(UTC)
        if replaced_by_token_id is not None:
            refresh_token.replaced_by_token_id = replaced_by_token_id
        await self.session.flush()
