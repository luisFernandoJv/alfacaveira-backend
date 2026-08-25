import pytest

from app.models.enums import NotificationCategory
from app.services.platform.notification_preference_service import (
    NotificationPreferenceService,
)


@pytest.mark.parametrize(
    ("category", "in_app", "email", "expected"),
    [
        (NotificationCategory.COMMENT, False, False, (False, False)),
        (NotificationCategory.MARKETING, False, True, (False, True)),
        (NotificationCategory.BILLING, False, False, (True, True)),
        (NotificationCategory.PLAN, False, False, (True, True)),
        (NotificationCategory.SYSTEM, False, False, (True, True)),
    ],
)
def test_mandatory_categories_cannot_be_disabled(
    category, in_app, email, expected
):
    assert (
        NotificationPreferenceService.normalize(category, in_app, email)
        == expected
    )
