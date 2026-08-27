"""Adiciona imagem opcional por alternativa de questão.

A imagem do enunciado já existia via `question_attachments` (tabela
genérica). Alternativas nunca tiveram como guardar imagem — a tela de
conferência de questões passou a expor um campo de imagem por alternativa
no frontend antes de o backend suportar isso, e o valor era descartado
silenciosamente pelo Pydantic (campo desconhecido, sem erro). Esta
migration fecha essa lacuna.

Revision ID: 0028_add_alternative_image
Revises: 0027_notification_category
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0028_add_alternative_image"
down_revision: Union[str, None] = "0027_notification_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "question_alternatives",
        sa.Column("image_url", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("question_alternatives", "image_url")