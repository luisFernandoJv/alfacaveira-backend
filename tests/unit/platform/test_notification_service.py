import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.enums import NotificationCategory
from app.services.platform.notification_service import NotificationService


@pytest.mark.asyncio
async def test_create_notification_propagates_persistence_failure(monkeypatch):
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    repository = MagicMock()
    repository.add = AsyncMock(side_effect=RuntimeError("db unavailable"))

    preferences = MagicMock()
    preferences.is_in_app_enabled = AsyncMock(return_value=True)

    monkeypatch.setattr(
        "app.services.platform.notification_service.NotificationRepository",
        lambda _session: repository,
    )
    monkeypatch.setattr(
        "app.services.platform.notification_service.NotificationPreferenceService",
        lambda _session: preferences,
    )

    service = NotificationService(session)

    with pytest.raises(RuntimeError, match="db unavailable"):
        await service.create_notification(
            user_id=uuid.uuid4(),
            type="payment_approved",
            title="Pagamento aprovado",
            body="Pagamento confirmado.",
            category=NotificationCategory.BILLING,
        )

    repository.add.assert_awaited_once()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_notification_skips_when_in_app_is_disabled(monkeypatch):
    session = MagicMock()
    repository = MagicMock()
    repository.add = AsyncMock()

    preferences = MagicMock()
    preferences.is_in_app_enabled = AsyncMock(return_value=False)

    monkeypatch.setattr(
        "app.services.platform.notification_service.NotificationRepository",
        lambda _session: repository,
    )
    monkeypatch.setattr(
        "app.services.platform.notification_service.NotificationPreferenceService",
        lambda _session: preferences,
    )

    service = NotificationService(session)
    result = await service.create_notification(
        user_id=uuid.uuid4(),
        type="marketing",
        title="Novidade",
        body="Temos novidades.",
        category=NotificationCategory.MARKETING,
    )

    assert result is None
    repository.add.assert_not_awaited()
