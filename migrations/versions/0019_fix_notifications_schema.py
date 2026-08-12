# migrations/versions/0019_fix_notifications_schema.py
"""fix_notifications_schema

A migration 0018 usava `CREATE TABLE IF NOT EXISTS notifications`. Como a
tabela `notifications` já existia no banco (de uma versão anterior, com um
schema diferente — ver DECISIONS.md ADR sobre renomear `metadata` para
`payload`), esse `CREATE TABLE IF NOT EXISTS` foi um NO-OP: o Alembic
marcou 0018 como aplicada, mas as colunas novas nunca foram criadas de
fato na tabela real.

Sintoma em produção:
    asyncpg.exceptions.UndefinedColumnError: column "link" of relation
    "notifications" does not exist

Esta migration corrige o schema real usando `ALTER TABLE ... ADD COLUMN
IF NOT EXISTS` para cada coluna esperada pelo model
`app/models/platform/notification.py`, de forma idempotente — segura de
rodar mesmo que algumas colunas já existam.

Revision ID: 0019_fix_notifications_schema
Revises: 0018_add_notifications
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019_fix_notifications_schema"
down_revision: Union[str, None] = "0018_add_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Se por acaso existir uma coluna antiga "metadata" (de uma versão
    # anterior do model, antes do rename documentado no ADR), migra o
    # conteúdo dela para "payload" antes de tudo.
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'notifications' AND column_name = 'metadata'
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'notifications' AND column_name = 'payload'
        ) THEN
            ALTER TABLE notifications RENAME COLUMN metadata TO payload;
        END IF;
    END $$;
    """)

    # Garante cada coluna esperada pelo model atual. Idempotente: não
    # falha se a coluna já existir.
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link VARCHAR(500)")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'unread'")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS type VARCHAR(50)")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS title VARCHAR(255)")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS body TEXT")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()")

    # Garante os índices esperados (idempotente).
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
    # Downgrade intencionalmente não remove colunas — reverter isso
    # arriscaria apagar dados de notificações reais. Se necessário,
    # reverta manualmente.
    pass