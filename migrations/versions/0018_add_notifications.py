# migrations/versions/0018_add_notifications.py
"""Adiciona tabela de notificações.

Revision ID: 0018_add_notifications
Revises: 0017_create_reviews_table
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0018_add_notifications"
down_revision: Union[str, None] = "0017_create_reviews_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar tabela notifications
    op.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        type VARCHAR(50) NOT NULL,
        title VARCHAR(255) NOT NULL,
        body TEXT NOT NULL,
        link VARCHAR(500),
        status VARCHAR(20) NOT NULL DEFAULT 'unread',
        read_at TIMESTAMP WITH TIME ZONE,
        payload JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )
    """)

    # Criar índices
    op.execute("""
    CREATE INDEX IF NOT EXISTS ix_notifications_user_id_status 
    ON notifications(user_id, status)
    """)
    
    op.execute("""
    CREATE INDEX IF NOT EXISTS ix_notifications_user_id_created_at 
    ON notifications(user_id, created_at DESC)
    """)
    
    op.execute("""
    CREATE INDEX IF NOT EXISTS ix_notifications_type 
    ON notifications(type)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications CASCADE")