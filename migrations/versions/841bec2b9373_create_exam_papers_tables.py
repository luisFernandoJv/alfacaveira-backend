"""create_exam_papers_tables

Revision ID: 0014_create_exam_papers_tables
Revises: b62d319494dd
Create Date: 2026-08-11 12:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014_create_exam_papers_tables"
down_revision: Union[str, None] = "b62d319494dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar tabela exam_papers
    op.execute("""
    CREATE TABLE IF NOT EXISTS exam_papers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title VARCHAR(255) NOT NULL,
        description TEXT,
        exam_board_id UUID NOT NULL REFERENCES exam_boards(id) ON DELETE RESTRICT,
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
        year INTEGER NOT NULL,
        total_questions INTEGER NOT NULL,
        pdf_url VARCHAR(500),
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )
    """)

    # Criar índices
    op.execute("CREATE INDEX IF NOT EXISTS idx_exam_papers_exam_board_id ON exam_papers(exam_board_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_exam_papers_organization_id ON exam_papers(organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_exam_papers_year ON exam_papers(year)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_exam_papers_is_active ON exam_papers(is_active)")

    # Criar tabela exam_paper_questions
    op.execute("""
    CREATE TABLE IF NOT EXISTS exam_paper_questions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        exam_paper_id UUID NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE,
        question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
        position INTEGER NOT NULL
    )
    """)

    # Criar índices
    op.execute("CREATE INDEX IF NOT EXISTS idx_exam_paper_questions_exam_paper_id ON exam_paper_questions(exam_paper_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_exam_paper_questions_question_id ON exam_paper_questions(question_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS exam_paper_questions CASCADE")
    op.execute("DROP TABLE IF EXISTS exam_papers CASCADE")