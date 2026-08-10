"""Dunning (PROMPT 11, roadmap item 11): adiciona rastreamento de
recobrança à assinatura inadimplente.

Três colunas novas em `subscriptions`, todas nullable/com default seguro
para não quebrar linhas existentes:

- `dunning_attempts` (INTEGER NOT NULL DEFAULT 0): tentativas de
  recobrança já feitas no ciclo de inadimplência atual.
- `dunning_next_retry_at` (TIMESTAMPTZ NULL): próxima tentativa elegível.
- `dunning_grace_period_ends_at` (TIMESTAMPTZ NULL): prazo final do grace
  period, após o qual a assinatura expira independentemente de tentativas
  restantes.

Nenhuma linha existente muda de significado: assinaturas que já estão
INADIMPLENTE antes desta migration ficam com os três campos em seus
defaults (0 / NULL / NULL) — o job de dunning (`app/workers/
subscription_dunning.py`) trata `dunning_grace_period_ends_at IS NULL`
como "nunca entra no filtro de expiração automática", então uma
assinatura inadimplente herdada de antes desta migration não é expirada
de surpresa; ela só passa a ter esses campos populados na próxima vez que
`mark_payment_failed` a mover para INADIMPLENTE a partir de ATIVA (o que
não deveria acontecer para quem já está INADIMPLENTE — ver docstring de
`SubscriptionService.mark_payment_failed`). Registrado como pendência
(ver docs/DECISIONS.md, ADR-027) para backfill manual se necessário.

Revision ID: 0009_dunning
Revises: 0008_renew_payment_idem
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_dunning"
down_revision: str | None = "0008_renew_payment_idem"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("dunning_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "subscriptions",
        sa.Column("dunning_next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("dunning_grace_period_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Remove o server_default depois do backfill implícito do ADD COLUMN —
    # mesmo padrão do resto do projeto (a coluna continua NOT NULL, só o
    # default explícito passa a ser responsabilidade do lado da aplicação,
    # não do schema).
    op.alter_column("subscriptions", "dunning_attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("subscriptions", "dunning_grace_period_ends_at")
    op.drop_column("subscriptions", "dunning_next_retry_at")
    op.drop_column("subscriptions", "dunning_attempts")