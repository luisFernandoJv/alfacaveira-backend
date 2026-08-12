"""create_reviews_table

Revision ID: 0013_create_reviews_table
Revises: c042a28b40ea
Create Date: 2026-08-11 15:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013_create_reviews_table"
down_revision: Union[str, None] = "c042a28b40ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar ENUMs
    op.execute("CREATE TYPE review_status AS ENUM ('pendente', 'em_andamento', 'concluida', 'pular')")
    op.execute("CREATE TYPE review_priority AS ENUM ('alta', 'media', 'baixa')")

    # Criar tabela reviews
    op.execute("""
    CREATE TABLE reviews (
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

    # Criar índices
    op.execute("CREATE INDEX idx_reviews_user_id ON reviews(user_id)")
    op.execute("CREATE INDEX idx_reviews_question_id ON reviews(question_id)")
    op.execute("CREATE INDEX idx_reviews_status ON reviews(status)")
    op.execute("CREATE INDEX idx_reviews_due_date ON reviews(due_date)")
    op.execute("CREATE INDEX idx_reviews_priority ON reviews(priority)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reviews CASCADE")
    op.execute("DROP TYPE IF EXISTS review_priority")
    op.execute("DROP TYPE IF EXISTS review_status")