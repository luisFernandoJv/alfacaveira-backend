"""Idempotência por evento para `renew_subscription` (ADR-022 achado,
ADR-023 decisão): adiciona `payment_id` nullable em `subscription_history`
+ FK para `payments.id` (ON DELETE SET NULL — perder o `Payment` não deve
apagar a linha de auditoria) + índice único parcial
`(subscription_id, payment_id) WHERE payment_id IS NOT NULL`.

Não altera nenhuma linha existente: toda entrada de `subscription_history`
criada antes desta migration fica com `payment_id = NULL` (nunca colidem
entre si porque o índice é parcial — só linhas com `payment_id` não-nulo
entram no índice único).

`change_plan` (ADR-023) não recebeu nenhuma coluna/índice equivalente
nesta migration: as proteções já existentes (CAS + guard "já está neste
plano") já eliminam o risco de duplicação financeira sem mudança de
schema — ver docs/DECISIONS.md ADR-023 para o raciocínio completo.

NOTA (correção pós-sessão): o revision id original desta migration
(`0008_renew_subscription_payment_idempotency`, 43 caracteres) estourava
o `VARCHAR(32)` padrão da tabela `alembic_version` — `alembic upgrade
head` falhava em `StringDataRightTruncationError` no UPDATE final de
`alembic_version.version_num` (a migration inteira revertia, por DDL
transacional, sem deixar nada aplicado pela metade). Renomeado para
`0008_renew_payment_idem` (23 caracteres). Se você já tentou rodar a
versão antiga desta migration, nada foi de fato aplicado no banco — pode
rodar esta normalmente.

Revision ID: 0008_renew_payment_idem
Revises: 0007_subscription_state_machine
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_renew_payment_idem"
down_revision: str | None = "0007_subscription_state_machine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscription_history",
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_subscription_history_payment_id_payments",
        "subscription_history",
        "payments",
        ["payment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Índice único PARCIAL: só cobre linhas com payment_id preenchido — o
    # histórico legado (payment_id NULL) nunca colide entre si, e novas
    # entradas de renovação com o mesmo (subscription_id, payment_id) são
    # rejeitadas pelo banco (backstop final contra corrida real, além da
    # checagem aplicativa em SubscriptionService.renew_subscription).
    op.execute(
        """CREATE UNIQUE INDEX ux_subscription_history_payment """
        """ON subscription_history (subscription_id, payment_id) """
        """WHERE payment_id IS NOT NULL"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_subscription_history_payment")
    op.drop_constraint(
        "fk_subscription_history_payment_id_payments",
        "subscription_history",
        type_="foreignkey",
    )
    op.drop_column("subscription_history", "payment_id")
