"""add current_question_index to training_sessions

Revision ID: 0004_training_session_position
Revises: 0003_user_question_states
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_training_session_position"
down_revision: Union[str, None] = "0003_user_question_states"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Posição (índice, 0-based) da questão que o aluno estava vendo por
    # último na sessão — usada para restaurar `/questoes/resolver` no
    # mesmo ponto após reload/fechar e reabrir a aba, em vez de sempre
    # voltar para a questão 0. `server_default="0"` garante que sessões já
    # existentes (criadas antes desta migration) sejam retrocompatíveis
    # sem precisar de um backfill separado.
    op.add_column(
        "training_sessions",
        sa.Column(
            "current_question_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("training_sessions", "current_question_index")