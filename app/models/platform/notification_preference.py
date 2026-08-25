"""Preferências de entrega de notificações por usuário e categoria."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import NotificationCategory


class NotificationPreference(UUIDPKMixin, TimestampMixin, Base):
    """Uma preferência por usuário/categoria."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "category",
            name="uq_notification_preferences_user_category",
        ),
        Index("ix_notification_preferences_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[NotificationCategory] = mapped_column(
        PGEnum(
            NotificationCategory,
            name="notification_category",
            create_type=False,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
    )
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped["User"] = relationship()
