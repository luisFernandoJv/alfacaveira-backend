"""Models do contexto 'platform' (notificações e administração)."""

from app.models.platform.admin_audit_log import AdminAuditLog
from app.models.platform.notification import Notification

__all__ = ["Notification", "AdminAuditLog"]
