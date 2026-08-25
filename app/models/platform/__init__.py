"""Models do contexto 'platform' (notificações e administração)."""

from app.models.platform.admin_audit_log import AdminAuditLog
from app.models.platform.notification import Notification
from app.models.platform.notification_preference import NotificationPreference

__all__ = ["Notification", "NotificationPreference", "AdminAuditLog"]
