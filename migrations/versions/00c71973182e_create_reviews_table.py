"""create_reviews_table

Revision ID: 0017_create_reviews_table
Revises: 0016_add_comments
Create Date: 2026-08-11 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0017_create_reviews_table"
down_revision: Union[str, None] = "0016_add_comments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar ENUMs com verificação
    op.execute("""
    DO $$ 
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'review_status') THEN
            CREATE TYPE review_status AS ENUM ('pendente', 'em_andamento', 'concluida', 'pular');
        END IF;
    END $$;
    """)

    op.execute("""
    DO $$ 
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'review_priority') THEN
            CREATE TYPE review_priority AS ENUM ('alta', 'media', 'baixa');
        END IF;
    END $$;
    """)

    # Criar tabela reviews (se não existir)
    op.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
        status review_status NOT NULL DEFAULT 'pendente',
        priority review_priority NOT NULL DEFAULT 'media',
        due_date DATE NOT NULL,
        last_reviewed_at TIMESTAMP WITH TIME ZONE,
        review_count INTEGER NOT NULL DEFAULT 0,
        consecutive_correct INTEGER NOT NULL DEFAULT 0,
        interval_days INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )
    """)

    # Criar índices (se não existirem)
    op.execute("CREATE INDEX IF NOT EXISTS ix_reviews_user_id ON reviews(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reviews_question_id ON reviews(question_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reviews_status ON reviews(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reviews_due_date ON reviews(due_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reviews_priority ON reviews(priority)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reviews CASCADE")
    op.execute("DROP TYPE IF EXISTS review_priority")
    op.execute("DROP TYPE IF EXISTS review_status")