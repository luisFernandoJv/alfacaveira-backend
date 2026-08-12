# migrations/versions/0020_add_notebooks.py
"""Adiciona tabelas de cadernos (notebooks).

Revision ID: 0020_add_notebooks
Revises: 0019_fix_notifications_schema
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0020_add_notebooks"
down_revision: Union[str, None] = "0019_fix_notifications_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar tabela notebook_folders
    op.execute("""
    CREATE TABLE notebook_folders (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        parent_id UUID REFERENCES notebook_folders(id) ON DELETE CASCADE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )
    """)
    op.execute("CREATE INDEX idx_notebook_folders_user_id ON notebook_folders(user_id)")
    op.execute("CREATE INDEX idx_notebook_folders_parent_id ON notebook_folders(parent_id)")

    # Criar tabela notebook_tags
    op.execute("""
    CREATE TABLE notebook_tags (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(80) NOT NULL,
        slug VARCHAR(90) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )
    """)
    op.execute("CREATE INDEX idx_notebook_tags_user_id ON notebook_tags(user_id)")
    op.execute("CREATE UNIQUE INDEX idx_notebook_tags_slug ON notebook_tags(slug)")

    # Criar tabela notebooks
    op.execute("""
    CREATE TABLE notebooks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        is_favorite BOOLEAN NOT NULL DEFAULT false,
        folder_id UUID REFERENCES notebook_folders(id) ON DELETE SET NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )
    """)
    op.execute("CREATE INDEX idx_notebooks_user_id ON notebooks(user_id)")
    op.execute("CREATE INDEX idx_notebooks_folder_id ON notebooks(folder_id)")

    # Criar tabela notebook_questions
    op.execute("""
    CREATE TABLE notebook_questions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
        question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
        note TEXT,
        added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        UNIQUE(notebook_id, question_id)
    )
    """)
    op.execute("CREATE INDEX idx_notebook_questions_notebook_id ON notebook_questions(notebook_id)")
    op.execute("CREATE INDEX idx_notebook_questions_question_id ON notebook_questions(question_id)")

    # Criar tabela notebook_tag_links (N:N)
    op.execute("""
    CREATE TABLE notebook_tag_links (
        notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
        tag_id UUID NOT NULL REFERENCES notebook_tags(id) ON DELETE CASCADE,
        PRIMARY KEY (notebook_id, tag_id)
    )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notebook_tag_links CASCADE")
    op.execute("DROP TABLE IF EXISTS notebook_questions CASCADE")
    op.execute("DROP TABLE IF EXISTS notebooks CASCADE")
    op.execute("DROP TABLE IF EXISTS notebook_tags CASCADE")
    op.execute("DROP TABLE IF EXISTS notebook_folders CASCADE")