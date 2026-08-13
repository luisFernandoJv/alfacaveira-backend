# migrations/versions/0021_fix_notebooks_schema.py
"""Corrige schema de cadernos (notebooks).

A migration 0020_add_notebooks criou as tabelas de cadernos mas com alguns
problemas de design:
1. notebook_tags tinha user_id (tags devem ser globais)
2. Faltava UNIQUE(user_id, name) em notebooks e notebook_folders
3. notebook_questions tinha nota (nota é global via user_question_states)
4. Índices usavam nomenclatura 'idx_' em vez de 'ix_'

Revision ID: 0021_fix_notebooks_schema
Revises: 0020_add_notebooks
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0021_fix_notebooks_schema"
down_revision: Union[str, None] = "0020_add_notebooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================================================================== #
    # 1. Corrigir notebook_tags (remover user_id, adicionar UNIQUE name)  #
    # ==================================================================== #
    
    # Verificar se user_id existe
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'notebook_tags' AND column_name = 'user_id'
        ) THEN
            ALTER TABLE notebook_tags DROP COLUMN user_id CASCADE;
        END IF;
    END $$;
    """)
    
    # Adicionar UNIQUE name se não existir
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'notebook_tags_name_key'
        ) THEN
            ALTER TABLE notebook_tags ADD CONSTRAINT notebook_tags_name_key UNIQUE (name);
        END IF;
    END $$;
    """)
    
    # ==================================================================== #
    # 2. Corrigir notebooks (adicionar UNIQUE user_id, name)              #
    # ==================================================================== #
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_notebook_user_name'
        ) THEN
            ALTER TABLE notebooks ADD CONSTRAINT uq_notebook_user_name UNIQUE (user_id, name);
        END IF;
    END $$;
    """)
    
    # ==================================================================== #
    # 3. Corrigir notebook_folders (adicionar UNIQUE user_id, name)       #
    # ==================================================================== #
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_notebook_folder_user_name'
        ) THEN
            ALTER TABLE notebook_folders ADD CONSTRAINT uq_notebook_folder_user_name UNIQUE (user_id, name);
        END IF;
    END $$;
    """)
    
    # ==================================================================== #
    # 4. Remover note de notebook_questions (nota é global)              #
    # ==================================================================== #
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'notebook_questions' AND column_name = 'note'
        ) THEN
            ALTER TABLE notebook_questions DROP COLUMN note CASCADE;
        END IF;
    END $$;
    """)
    
    # ==================================================================== #
    # 5. Padronizar índices (ix_ em vez de idx_)                         #
    # ==================================================================== #
    
    # Remover índices antigos (se existirem)
    op.execute("DROP INDEX IF EXISTS idx_notebook_folders_user_id")
    op.execute("DROP INDEX IF EXISTS idx_notebook_folders_parent_id")
    op.execute("DROP INDEX IF EXISTS idx_notebook_tags_user_id")
    op.execute("DROP INDEX IF EXISTS idx_notebook_tags_slug")
    op.execute("DROP INDEX IF EXISTS idx_notebooks_user_id")
    op.execute("DROP INDEX IF EXISTS idx_notebooks_folder_id")
    op.execute("DROP INDEX IF EXISTS idx_notebook_questions_notebook_id")
    op.execute("DROP INDEX IF EXISTS idx_notebook_questions_question_id")
    
    # Criar índices com nomenclatura padronizada
    op.execute("CREATE INDEX ix_notebook_folders_user_id ON notebook_folders(user_id)")
    op.execute("CREATE INDEX ix_notebook_folders_parent_id ON notebook_folders(parent_id)")
    op.execute("CREATE INDEX ix_notebook_tags_slug ON notebook_tags(slug)")
    op.execute("CREATE INDEX ix_notebooks_user_id ON notebooks(user_id)")
    op.execute("CREATE INDEX ix_notebooks_folder_id ON notebooks(folder_id)")
    op.execute("CREATE INDEX ix_notebooks_user_id_favorite ON notebooks(user_id, is_favorite)")
    op.execute("CREATE INDEX ix_notebook_questions_notebook_id ON notebook_questions(notebook_id)")
    op.execute("CREATE INDEX ix_notebook_questions_question_id ON notebook_questions(question_id)")
    op.execute("CREATE INDEX ix_notebook_questions_added_at ON notebook_questions(added_at)")


def downgrade() -> None:
    # ==================================================================== #
    # 1. Remover constraints adicionadas                                   #
    # ==================================================================== #
    op.execute("ALTER TABLE notebooks DROP CONSTRAINT IF EXISTS uq_notebook_user_name")
    op.execute("ALTER TABLE notebook_folders DROP CONSTRAINT IF EXISTS uq_notebook_folder_user_name")
    
    # ==================================================================== #
    # 2. Restaurar user_id em notebook_tags (para downgrade)              #
    # ==================================================================== #
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'notebook_tags' AND column_name = 'user_id'
        ) THEN
            ALTER TABLE notebook_tags ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE;
            CREATE INDEX idx_notebook_tags_user_id ON notebook_tags(user_id);
        END IF;
    END $$;
    """)
    
    # ==================================================================== #
    # 3. Restaurar note em notebook_questions (para downgrade)            #
    # ==================================================================== #
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'notebook_questions' AND column_name = 'note'
        ) THEN
            ALTER TABLE notebook_questions ADD COLUMN note TEXT;
        END IF;
    END $$;
    """)
    
    # ==================================================================== #
    # 4. Restaurar índices antigos                                        #
    # ==================================================================== #
    op.execute("CREATE INDEX idx_notebook_folders_user_id ON notebook_folders(user_id)")
    op.execute("CREATE INDEX idx_notebook_folders_parent_id ON notebook_folders(parent_id)")
    op.execute("CREATE INDEX idx_notebook_tags_user_id ON notebook_tags(user_id)")
    op.execute("CREATE INDEX idx_notebook_tags_slug ON notebook_tags(slug)")
    op.execute("CREATE INDEX idx_notebooks_user_id ON notebooks(user_id)")
    op.execute("CREATE INDEX idx_notebooks_folder_id ON notebooks(folder_id)")
    op.execute("CREATE INDEX idx_notebook_questions_notebook_id ON notebook_questions(notebook_id)")
    op.execute("CREATE INDEX idx_notebook_questions_question_id ON notebook_questions(question_id)")