"""Máquina de estados de assinatura (PROMPT 05): introduz o valor 'pendente'
em `subscription_status` e o valor 'ativada' em `subscription_history_reason`.

Não altera a forma de nenhuma tabela — apenas adiciona valores aos tipos
ENUM já existentes (criados em `0001_initial_schema` e `0005_billing_features`).
Nenhuma linha existente é tocada: `Subscription.status` já era NOT NULL sem
default de banco (o default vem do lado do SQLAlchemy), então não há dado
legado para migrar.

Ver docs/DECISIONS.md ADR-014 para a decisão completa da máquina de estados.

Revision ID: 0007_subscription_state_machine
Revises: 0006_seed_billing_catalog
Create Date: 2026-08-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007_subscription_state_machine"
down_revision: Union[str, None] = "0006_seed_billing_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `ADD VALUE` em tipos ENUM do Postgres é irreversível dentro de uma
    # transação até ser commitada, mas pode ser executado dentro da
    # transação da migration normalmente, desde que o novo valor não seja
    # *usado* (em outro `INSERT`/`UPDATE`) na mesma transação — o que não
    # é o caso aqui, esta migration só adiciona os valores.
    op.execute("ALTER TYPE subscription_status ADD VALUE IF NOT EXISTS 'pendente'")
    op.execute("ALTER TYPE subscription_history_reason ADD VALUE IF NOT EXISTS 'ativada'")


def downgrade() -> None:
    # Postgres não suporta remover um valor de um tipo ENUM diretamente
    # (`DROP VALUE` não existe). Reverter de verdade exigiria recriar
    # `subscription_status`/`subscription_history_reason` do zero e
    # migrar todas as linhas que os usam — destrutivo e fora do escopo de
    # um downgrade de rotina. Se este downgrade for necessário algum dia,
    # tratar como uma migration própria, feita a mão, com o time ciente
    # de que linhas em status/reason 'pendente'/'ativada' (se houver)
    # precisam ser resolvidas antes.
    raise NotImplementedError(
        "Downgrade não suportado: Postgres não permite remover valores de "
        "um tipo ENUM diretamente. Ver docs/DECISIONS.md ADR-014."
    )