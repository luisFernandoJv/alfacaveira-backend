# migrations/versions/0011_renewal_reminder.py
"""Adiciona renewal_reminder_sent_at em subscriptions.

Revision ID: 0011_renewal_reminder
Revises: 0010_upgrade_downgrade_prorata
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_renewal_reminder"
down_revision: str | None = "0010_upgrade_downgrade_prorata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "renewal_reminder_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
            default=None,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "renewal_reminder_sent_at")