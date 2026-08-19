"""update_pro_plan_price

Corrige o preço oficial do plano Pro para R$ 59,90/mês (5990 centavos).

Contexto: `0006_seed_billing_catalog` criou o Pro com `price_cents=4990`
(R$ 49,90). A decisão comercial vigente (auditoria do funil Free/Padrão/
Pro) fixa Pro em R$ 59,90/mês — mesmo padrão de correção pós-seed já usado
por `0023_update_standard_plan_to_padrao` para o plano Padrão.

Revision ID: 0024_update_pro_price
Revises: 0023_update_padrao
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op

# Identificadores da revisão (Alembic)
revision: str = '0024_update_pro_price'
down_revision: Union[str, None] = '0023_update_padrao'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE plans
        SET price_cents = 5990
        WHERE slug = 'pro';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE plans
        SET price_cents = 4990
        WHERE slug = 'pro';
        """
    )
