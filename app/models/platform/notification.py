# app/models/platform/notification.py
"""Modelo de notificações do sistema."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class Notification(UUIDPKMixin, TimestampMixin, Base):
    """Notificação de um usuário."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_status", "user_id", "status"),
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        Index("ix_notifications_type", "type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unread"
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=False, default=dict)

    # Relacionamentos
    user: Mapped["User"] = relationship()