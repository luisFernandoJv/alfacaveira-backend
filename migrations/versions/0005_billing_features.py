"""Módulo de Billing: Feature Gate (features, plan_features) e auditoria de
assinatura (subscription_history).

Não altera nenhuma tabela existente de billing (`plans`, `subscriptions`,
`payments`) além de um índice único parcial em `subscriptions`, que garante
no máximo 1 assinatura ATIVA por usuário sem mudar a forma da tabela.

Revision ID: 0005_billing_features
Revises: 0004_training_session_position
Create Date: 2026-08-06
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_billing_features"
down_revision: Union[str, None] = "0004_training_session_position"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE feature_key AS ENUM ("
        "'daily_questions', 'notebooks', 'notebook_max_questions', "
        "'simulados', 'flashcards', 'estatisticas', 'dashboard_completo', "
        "'ai_explicacao_questao', 'ai_resumos', 'ai_cronograma', "
        "'ai_analise_desempenho', 'analytics_avancado'"
        ")"
    )
    op.execute("CREATE TYPE feature_kind AS ENUM ('boolean', 'quota')")
    op.execute(
        "CREATE TYPE subscription_history_reason AS ENUM ("
        "'criada', 'renovada', 'upgrade', 'downgrade', 'cancelada', "
        "'reativada', 'expirada', 'pagamento_falhou'"
        ")"
    )

    op.execute("""CREATE TABLE features (
	key feature_key NOT NULL,
	kind feature_kind NOT NULL,
	name VARCHAR(150) NOT NULL,
	description VARCHAR(500),
	is_active BOOLEAN NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (key)
)""")
    op.execute("""CREATE INDEX ix_features_key ON features (key)""")

    op.execute("""CREATE TABLE plan_features (
	plan_id UUID NOT NULL,
	feature_id UUID NOT NULL,
	quota_limit INTEGER,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(plan_id) REFERENCES plans (id) ON DELETE CASCADE,
	FOREIGN KEY(feature_id) REFERENCES features (id) ON DELETE CASCADE,
	UNIQUE (plan_id, feature_id)
)""")
    op.execute("""CREATE INDEX ix_plan_features_plan_id ON plan_features (plan_id)""")
    op.execute("""CREATE INDEX ix_plan_features_feature_id ON plan_features (feature_id)""")

    op.execute("""CREATE TABLE subscription_history (
	subscription_id UUID NOT NULL,
	from_plan_id UUID,
	to_plan_id UUID NOT NULL,
	from_status subscription_status,
	to_status subscription_status NOT NULL,
	reason subscription_history_reason NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(subscription_id) REFERENCES subscriptions (id) ON DELETE CASCADE,
	FOREIGN KEY(from_plan_id) REFERENCES plans (id) ON DELETE SET NULL,
	FOREIGN KEY(to_plan_id) REFERENCES plans (id) ON DELETE RESTRICT
)""")
    op.execute(
        """CREATE INDEX ix_subscription_history_subscription_id """
        """ON subscription_history (subscription_id)"""
    )

    # Garante no máximo 1 assinatura ATIVA por usuário. Índice parcial (não
    # UNIQUE de coluna inteira) porque um usuário pode ter várias assinaturas
    # ao longo do tempo (canceladas/expiradas) — só a ativa precisa ser única.
    op.execute(
        """CREATE UNIQUE INDEX ux_subscriptions_one_active_per_user """
        """ON subscriptions (user_id) WHERE status = 'ativa'"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_subscriptions_one_active_per_user")
    op.execute("DROP TABLE IF EXISTS subscription_history CASCADE")
    op.execute("DROP TABLE IF EXISTS plan_features CASCADE")
    op.execute("DROP TABLE IF EXISTS features CASCADE")
    op.execute("DROP TYPE IF EXISTS subscription_history_reason")
    op.execute("DROP TYPE IF EXISTS feature_kind")
    op.execute("DROP TYPE IF EXISTS feature_key")