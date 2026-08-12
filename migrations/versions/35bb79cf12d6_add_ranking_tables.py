"""add_ranking_tables

Revision ID: 35bb79cf12d6
Revises: 0014_create_exam_papers_tables
Create Date: 2026-08-11 21:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "35bb79cf12d6"
down_revision: Union[str, None] = "0014_create_exam_papers_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar tabela user_rankings
    op.execute("""
    CREATE TABLE IF NOT EXISTS user_rankings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        total_points INTEGER NOT NULL DEFAULT 0,
        questions_answered INTEGER NOT NULL DEFAULT 0,
        correct_answers INTEGER NOT NULL DEFAULT 0,
        accuracy FLOAT NOT NULL DEFAULT 0.0,
        streak_days INTEGER NOT NULL DEFAULT 0,
        weekly_points INTEGER NOT NULL DEFAULT 0,
        monthly_points INTEGER NOT NULL DEFAULT 0,
        rank INTEGER,
        rank_weekly INTEGER,
        rank_monthly INTEGER,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )
    """)

    # Criar índices
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_rankings_user_id ON user_rankings(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_rankings_rank ON user_rankings(rank)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_rankings_total_points ON user_rankings(total_points)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_rankings CASCADE")