"""Renomeia o plano 'standard' para 'Padrão' e atualiza o preço para R$ 39,90.

Decisão comercial: o plano antigamente chamado "Standard" (R$ 29,90/mês)
passa a se chamar "Padrão" e custa R$ 39,90/mês. O `slug` ("standard")
permanece inalterado para não quebrar referências existentes (feature
gating, assinaturas já criadas, testes, etc.) — apenas o `name` (rótulo
exibido) e o `price_cents` mudam.

Não mexe em `plan_features` nem no cache `plans.features` — a composição
de features do plano não muda, só o nome e o preço.

Revision ID: 0023_update_standard_plan_to_padrao
Revises: 0022_add_question_reports
Create Date: 2026-08-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_update_standard_plan_to_padrao"
down_revision: Union[str, None] = "0022_add_question_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NAME = "Standard"
NEW_NAME = "Padrão"
OLD_PRICE_CENTS = 2990
NEW_PRICE_CENTS = 3990
PLAN_SLUG = "standard"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE plans
            SET name = :new_name,
                price_cents = :new_price,
                updated_at = now()
            WHERE slug = :slug
            """
        ),
        {"new_name": NEW_NAME, "new_price": NEW_PRICE_CENTS, "slug": PLAN_SLUG},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE plans
            SET name = :old_name,
                price_cents = :old_price,
                updated_at = now()
            WHERE slug = :slug
            """
        ),
        {"old_name": OLD_NAME, "old_price": OLD_PRICE_CENTS, "slug": PLAN_SLUG},
    )
