"""Token opaco de recuperação de senha (hash armazenado), de uso único."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class PasswordResetToken(UUIDPKMixin, TimestampMixin, Base):
    """Token de redefinição de senha. O valor em texto puro nunca é persistido.

    Mesmo padrão do `RefreshToken` (token aleatório de alta entropia, hash
    SHA-256 indexado para lookup), mas de uso único (`used_at`) em vez de
    rotação: uma vez consumido — ou substituído por um novo pedido — não
    pode ser reaproveitado.
    """

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="password_reset_tokens")
