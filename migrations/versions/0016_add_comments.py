"""add_comments

Revision ID: 0016_add_comments
Revises: 35bb79cf12d6
Create Date: 2026-08-11 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0016_add_comments"
down_revision: Union[str, None] = "35bb79cf12d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar ENUMs
    op.execute("CREATE TYPE comment_status AS ENUM ('publicado', 'pendente', 'denunciado', 'removido', 'bloqueado')")
    op.execute("CREATE TYPE comment_vote_type AS ENUM ('up', 'down')")

    # Criar tabela comments
    op.execute("""
    CREATE TABLE comments (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
        parent_id UUID REFERENCES comments(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        status comment_status NOT NULL DEFAULT 'publicado',
        upvotes INTEGER NOT NULL DEFAULT 0,
        downvotes INTEGER NOT NULL DEFAULT 0,
        report_count INTEGER NOT NULL DEFAULT 0,
        is_edited BOOLEAN NOT NULL DEFAULT false,
        edited_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )
    """)

    # Criar índices
    op.execute("CREATE INDEX ix_comments_question_id_status ON comments(question_id, status)")
    op.execute("CREATE INDEX ix_comments_user_id ON comments(user_id)")
    op.execute("CREATE INDEX ix_comments_parent_id ON comments(parent_id)")

    # Criar tabela comment_votes
    op.execute("""
    CREATE TABLE comment_votes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        comment_id UUID NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
        vote_type comment_vote_type NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        UNIQUE(user_id, comment_id)
    )
    """)

    # Criar índices
    op.execute("CREATE INDEX ix_comment_votes_user_id ON comment_votes(user_id)")
    op.execute("CREATE INDEX ix_comment_votes_comment_id ON comment_votes(comment_id)")

    # Criar tabela comment_reports
    op.execute("""
    CREATE TABLE comment_reports (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        comment_id UUID NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
        reason TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        resolved_at TIMESTAMP WITH TIME ZONE,
        resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(user_id, comment_id)
    )
    """)

    # Criar índices
    op.execute("CREATE INDEX ix_comment_reports_user_id ON comment_reports(user_id)")
    op.execute("CREATE INDEX ix_comment_reports_comment_id ON comment_reports(comment_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS comment_reports CASCADE")
    op.execute("DROP TABLE IF EXISTS comment_votes CASCADE")
    op.execute("DROP TABLE IF EXISTS comments CASCADE")
    op.execute("DROP TYPE IF EXISTS comment_vote_type")
    op.execute("DROP TYPE IF EXISTS comment_status")