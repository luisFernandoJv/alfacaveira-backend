# app/schemas/platform/notification.py
"""Schemas de notificações."""

import uuid
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    """Resposta de uma notificação."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    body: str
    link: Optional[str] = None
    status: str
    read_at: Optional[datetime] = None
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class NotificationListResponse(BaseModel):
    """Lista paginada de notificações."""

    items: list[NotificationResponse]
    total: int
    unread_count: int
    next_cursor: Optional[str] = None
    has_more: bool = False


class NotificationMarkReadRequest(BaseModel):
    """Request para marcar notificações como lidas."""

    notification_ids: Optional[List[uuid.UUID]] = None
    mark_all: bool = False