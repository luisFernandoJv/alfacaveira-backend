"""Repositório de acesso a dados de `PasswordResetToken`."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.identity.password_reset_token import PasswordResetToken
from app.repositories.base import BaseRepository


class PasswordResetTokenRepository(BaseRepository[PasswordResetToken]):
    model = PasswordResetToken

    async def get_valid_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        """Retorna o token apenas se existir, não tiver sido usado e não estar expirado.

        A validação de expiração/uso é feita aqui (e não só no service) para
        que a query já reflita a regra de negócio central deste repositório.
        """
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(UTC),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_used(self, token: PasswordResetToken) -> None:
        token.used_at = datetime.now(UTC)
        await self.session.flush()

    async def invalidate_all_for_user(self, user_id: uuid.UUID) -> None:
        """Invalida (marca como usados) todos os tokens ainda válidos do usuário.

        Chamado ao emitir um novo pedido de recuperação: evita que um link
        antigo enviado por e-mail continue funcionando depois de um pedido
        mais recente.
        """
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        result = await self.session.execute(stmt)
        now = datetime.now(UTC)
        for token in result.scalars().all():
            token.used_at = now
        await self.session.flush()
