"""Upgrade/downgrade com pró-rata (PROMPT 12).

Adiciona suporte a downgrade agendado (`pending_plan_id`) e upgrade
com cobrança imediata da diferença pró-rata.

Colunas novas em `subscriptions`:
- `pending_plan_id` (UUID, nullable, FK plans.id): plano para o qual a
  assinatura será trocada no próximo ciclo de cobrança (usado para
  downgrade). NULL quando não há downgrade agendado.
- `pending_plan_effective_at` (TIMESTAMPTZ, nullable): data em que o
  downgrade entra em vigor (normalmente `current_period_end`). NULL
  quando não há downgrade agendado.

Também adiciona o valor `UPGRADE_PENDENTE` ao enum `subscription_history_reason`
para rastrear upgrades pendentes de confirmação de pagamento (gateway
assíncrono).

Migration idempotente: adiciona as colunas e o valor ENUM se não existirem.

Revision ID: 0010_upgrade_downgrade_prorata
Revises: 0009_dunning
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_upgrade_downgrade_prorata"
down_revision: str | None = "0009_dunning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ================================================================== #
    # 1. Adicionar colunas em subscriptions                               #
    # ================================================================== #
    op.add_column(
        "subscriptions",
        sa.Column(
            "pending_plan_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "pending_plan_effective_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ================================================================== #
    # 2. FK e índices                                                    #
    # ================================================================== #
    op.create_foreign_key(
        "fk_subscriptions_pending_plan_id_plans",
        "subscriptions",
        "plans",
        ["pending_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_subscriptions_pending_plan_id",
        "subscriptions",
        ["pending_plan_id"],
    )

    # Índice composto para consultas de downgrade agendado no worker
    # (status + pending_plan_id + pending_plan_effective_at)
    op.create_index(
        "ix_subscriptions_pending_downgrade",
        "subscriptions",
        ["status", "pending_plan_id", "pending_plan_effective_at"],
        postgresql_where=sa.text(
            "status = 'ativa' AND pending_plan_id IS NOT NULL AND pending_plan_effective_at IS NOT NULL"
        ),
    )

    # ================================================================== #
    # 3. Adicionar valor UPGRADE_PENDENTE ao ENUM                        #
    # ================================================================== #
    # Postgres não permite ADD VALUE dentro de uma transação se o novo
    # valor for usado em INSERT/UPDATE na mesma transação. Como esta
    # migration só adiciona o valor ao enum (não insere nenhuma linha
    # usando-o), é seguro executar dentro da mesma transação.
    op.execute(
        "ALTER TYPE subscription_history_reason ADD VALUE IF NOT EXISTS 'upgrade_pendente'"
    )


def downgrade() -> None:
    # ================================================================== #
    # 1. Remover índices                                                 #
    # ================================================================== #
    op.drop_index(
        "ix_subscriptions_pending_downgrade",
        table_name="subscriptions",
        postgresql_where=sa.text(
            "status = 'ativa' AND pending_plan_id IS NOT NULL AND pending_plan_effective_at IS NOT NULL"
        ),
    )
    op.drop_index("ix_subscriptions_pending_plan_id", table_name="subscriptions")

    # ================================================================== #
    # 2. Remover FK                                                      #
    # ================================================================== #
    op.drop_constraint(
        "fk_subscriptions_pending_plan_id_plans",
        "subscriptions",
        type_="foreignkey",
    )

    # ================================================================== #
    # 3. Remover colunas                                                 #
    # ================================================================== #
    op.drop_column("subscriptions", "pending_plan_effective_at")
    op.drop_column("subscriptions", "pending_plan_id")

    # ================================================================== #
    # 4. Remover valor UPGRADE_PENDENTE do ENUM                         #
    # ================================================================== #
    # Postgres não suporta DROP VALUE em ENUM diretamente. Para remover
    # um valor, seria necessário recriar o tipo ENUM do zero, o que
    # exigiria migrar todas as colunas que o usam. Como este é um valor
    # que não é usado em nenhuma linha existente (foi adicionado agora),
    # e o downgrade é apenas para desenvolvimento/rollback, deixamos
    # como NotImplementedError com a instrução de como proceder.
    #
    # Se for absolutamente necessário remover este valor:
    # 1. Verificar se não há nenhuma linha usando 'upgrade_pendente'
    # 2. Criar um novo tipo ENUM sem o valor
    # 3. Migrar todas as colunas para o novo tipo
    # 4. Dropar o tipo antigo
    #
    # Isso é destrutivo e não é recomendado para rollback de rotina.
    raise NotImplementedError(
        "Downgrade do valor ENUM 'upgrade_pendente' não é suportado diretamente. "
        "Para reverter, recrie o tipo subscription_history_reason sem o valor "
        "e migre as colunas que o usam. Ver docs/DECISIONS.md para detalhes."
    )