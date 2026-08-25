"""Schemas de notificações."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import NotificationCategory


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    body: str
    link: str | None = None
    status: str
    read_at: datetime | None = None
    payload: dict = Field(default_factory=dict)
    created_at: datetime
    category: NotificationCategory = NotificationCategory.SYSTEM


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    next_cursor: str | None = None
    has_more: bool = False


class NotificationMarkReadRequest(BaseModel):
    notification_ids: list[uuid.UUID] | None = None
    mark_all: bool = False


class NotificationArchiveRequest(BaseModel):
    notification_ids: list[uuid.UUID] = Field(default_factory=list)


class NotificationPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: NotificationCategory
    in_app_enabled: bool
    email_enabled: bool
    mandatory: bool


class NotificationPreferencePatchItem(BaseModel):
    category: NotificationCategory
    in_app_enabled: bool | None = None
    email_enabled: bool | None = None


class NotificationPreferencesPatch(BaseModel):
    preferences: list[NotificationPreferencePatchItem] = Field(default_factory=list)


class NotificationBroadcastRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=5000)
    link: str | None = Field(default=None, max_length=500)
    segment: str = Field(default="all", pattern=r"^(all|free|standard|pro)$")
