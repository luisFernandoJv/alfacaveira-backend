"""update_standard_plan_to_padrao

Revision ID: 0023_update_standard_plan_to_padrao
Revises: 0022_add_question_reports
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores da revisão (Alembic)
revision: str = '0023_update_padrao'
down_revision: Union[str, None] = '0022_add_question_reports'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ATENÇÃO: No PostgreSQL, textos precisam estar obrigatoriamente 
    # entre aspas simples (''). Aspas duplas ("") farão o banco procurar 
    # por uma coluna com aquele nome.
    op.execute(
        """
        UPDATE plans 
        SET name = 'Padrão', price_cents = 3990 
        WHERE slug = 'standard';
        """
    )


def downgrade() -> None:
    # Reverte o plano de volta para o nome e preço anteriores, caso precise
    # desfazer a migração no futuro. 
    # (Ajuste o valor 2990 abaixo caso o preço antigo fosse diferente).
    op.execute(
        """
        UPDATE plans 
        SET name = 'Standard', price_cents = 2990 
        WHERE slug = 'standard';
        """
    )