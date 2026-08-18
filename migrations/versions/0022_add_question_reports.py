"""add_question_reports

Revision ID: 0022_add_question_reports
Revises: 0021_fix_notebooks_schema
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0022_add_question_reports"
down_revision: Union[str, None] = "0021_fix_notebooks_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar o tipo ENUM se não existir
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'question_report_reason') THEN
                CREATE TYPE question_report_reason AS ENUM (
                    'enunciado', 'gabarito', 'duplicada', 'classificacao', 'outro'
                );
            END IF;
        END
        $$;
        """
    )

    # Criar a tabela se não existir
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS question_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reason question_report_reason NOT NULL,
            details TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pendente',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
        """
    )

    # Índices (usando IF NOT EXISTS)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_question_reports_question_id') THEN
                CREATE INDEX ix_question_reports_question_id ON question_reports(question_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_question_reports_user_id') THEN
                CREATE INDEX ix_question_reports_user_id ON question_reports(user_id);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS question_reports CASCADE")
    op.execute("DROP TYPE IF EXISTS question_report_reason")