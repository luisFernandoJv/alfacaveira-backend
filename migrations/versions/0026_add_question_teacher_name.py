"""Adiciona nome do professor autor do gabarito comentado.

Revision ID: 0026_add_question_teacher_name
Revises: 0025_add_google_auth
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0026_add_question_teacher_name"
down_revision: Union[str, None] = "0025_add_google_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("teacher_name", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "teacher_name")