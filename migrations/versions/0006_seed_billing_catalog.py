"""Seed do catálogo de features e planos de assinatura (Free/Standard/Pro).

Garante que qualquer banco novo (inclusive produção) já nasça com o
catálogo de `features`, os `plans` e as ligações `plan_features` prontos —
sem isso, `FeatureGateService` quebra ao buscar o plano "free" como
fallback, e a landing (`Pricing.tsx`) não tem o que renderizar.

Segue exatamente o mesmo formato de cache que `PlanService._rebuild_features_cache`
grava em `plans.features` (JSONB): `{"<feature_key>": {"kind": ..., "quota_limit": ...}}`.

Revision ID: 0006_seed_billing_catalog
Revises: 0005_billing_features
Create Date: 2026-08-07
"""
import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_seed_billing_catalog"
down_revision: Union[str, None] = "0005_billing_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Sincronizado com `app/models/enums.py::FeatureKey/FeatureKind` e com o
# tipo `feature_key`/`feature_kind` criados em `0005_billing_features`.
# Movido de `scripts/seed_test_data.py` (FEATURE_CATALOG).
FEATURE_CATALOG: list[tuple[str, str, str, str]] = [
    ("daily_questions", "quota", "Questões por dia", "Quantidade de questões que o usuário pode responder por dia."),
    ("notebooks", "boolean", "Cadernos de questões", "Acesso à criação de cadernos de questões personalizados."),
    ("notebook_max_questions", "quota", "Questões por caderno", "Limite de questões por caderno de questões."),
    ("simulados", "boolean", "Simulados", "Acesso à realização de simulados cronometrados."),
    ("flashcards", "boolean", "Flashcards", "Acesso ao módulo de flashcards com revisão espaçada."),
    ("estatisticas", "boolean", "Estatísticas básicas", "Acesso às estatísticas básicas de desempenho."),
    ("dashboard_completo", "boolean", "Dashboard completo", "Acesso ao dashboard completo de acompanhamento de estudos."),
    ("ai_explicacao_questao", "boolean", "Explicação de questão por IA", "Explicação de questões geradas por IA."),
    ("ai_resumos", "boolean", "Resumos por IA", "Geração de resumos de conteúdo por IA."),
    ("ai_cronograma", "boolean", "Cronograma por IA", "Geração de cronograma de estudos por IA."),
    ("ai_analise_desempenho", "boolean", "Análise de desempenho por IA", "Análise de desempenho gerada por IA."),
    ("analytics_avancado", "boolean", "Analytics avançado", "Métricas avançadas de desempenho e evolução."),
]

# Movido de `scripts/seed_test_data.py` (PLAN_CATALOG). `quota_limit=None`
# numa feature QUOTA significa "ilimitado"; features BOOLEAN não recebem
# quota_limit.
PLAN_CATALOG: list[dict] = [
    {
        "slug": "free",
        "name": "Free",
        "price_cents": 0,
        "billing_period": "mensal",
        "features": {
            "daily_questions": 5,
            "flashcards": None,
            "estatisticas": None,
        },
    },
    {
        "slug": "standard",
        "name": "Standard",
        "price_cents": 2990,
        "billing_period": "mensal",
        "features": {
            "daily_questions": None,
            "notebooks": None,
            "notebook_max_questions": 50,
            "simulados": None,
            "flashcards": None,
            "estatisticas": None,
            "dashboard_completo": None,
        },
    },
    {
        "slug": "pro",
        "name": "Pro",
        "price_cents": 4990,
        "billing_period": "mensal",
        "features": {
            "daily_questions": None,
            "notebooks": None,
            "notebook_max_questions": None,
            "simulados": None,
            "flashcards": None,
            "estatisticas": None,
            "dashboard_completo": None,
            "ai_explicacao_questao": None,
            "ai_resumos": None,
            "ai_cronograma": None,
            "ai_analise_desempenho": None,
            "analytics_avancado": None,
        },
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. Catálogo de features (idempotente por `key`) ------------------ #
    feature_ids: dict[str, str] = {}
    feature_kinds: dict[str, str] = {}
    for key, kind, name, description in FEATURE_CATALOG:
        row = conn.execute(
            sa.text("SELECT id FROM features WHERE key = CAST(:key AS feature_key)"),
            {"key": key},
        ).first()
        if row is not None:
            feature_ids[key] = str(row[0])
            feature_kinds[key] = kind
            continue

        feature_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                """
                INSERT INTO features (id, key, kind, name, description, is_active, created_at, updated_at)
                VALUES (:id, CAST(:key AS feature_key), CAST(:kind AS feature_kind), :name, :description,
                        true, now(), now())
                """
            ),
            {
                "id": feature_id,
                "key": key,
                "kind": kind,
                "name": name,
                "description": description,
            },
        )
        feature_ids[key] = feature_id
        feature_kinds[key] = kind

    # --- 2. Planos + associação plan_features (idempotente por slug) ------ #
    for spec in PLAN_CATALOG:
        row = conn.execute(
            sa.text("SELECT id FROM plans WHERE slug = :slug"), {"slug": spec["slug"]}
        ).first()
        if row is not None:
            plan_id = str(row[0])
        else:
            plan_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    """
                    INSERT INTO plans
                        (id, name, slug, price_cents, billing_period, features, is_active, created_at, updated_at)
                    VALUES
                        (:id, :name, :slug, :price_cents, CAST(:billing_period AS billing_period),
                         CAST(:features AS JSONB), true, now(), now())
                    """
                ),
                {
                    "id": plan_id,
                    "name": spec["name"],
                    "slug": spec["slug"],
                    "price_cents": spec["price_cents"],
                    "billing_period": spec["billing_period"],
                    "features": json.dumps({}),
                },
            )

        cache: dict[str, dict] = {}
        for feature_key, quota_limit in spec["features"].items():
            feature_id = feature_ids[feature_key]

            existing_link = conn.execute(
                sa.text(
                    "SELECT id FROM plan_features WHERE plan_id = :plan_id AND feature_id = :feature_id"
                ),
                {"plan_id": plan_id, "feature_id": feature_id},
            ).first()
            if existing_link is None:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO plan_features
                            (id, plan_id, feature_id, quota_limit, created_at, updated_at)
                        VALUES
                            (:id, :plan_id, :feature_id, :quota_limit, now(), now())
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "plan_id": plan_id,
                        "feature_id": feature_id,
                        "quota_limit": quota_limit,
                    },
                )

            cache[feature_key] = {
                "kind": feature_kinds[feature_key],
                "quota_limit": quota_limit,
            }

        # --- 3. Reconstrói o cache `plans.features` (mesmo formato de
        # `PlanService._rebuild_features_cache`) --------------------------- #
        conn.execute(
            sa.text("UPDATE plans SET features = CAST(:features AS JSONB) WHERE id = :id"),
            {"features": json.dumps(cache), "id": plan_id},
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM plan_features WHERE plan_id IN (SELECT id FROM plans WHERE slug IN ('free', 'standard', 'pro'))"
    )
    op.execute("DELETE FROM plans WHERE slug IN ('free', 'standard', 'pro')")
    op.execute(
        "DELETE FROM features WHERE key IN ("
        "'daily_questions', 'notebooks', 'notebook_max_questions', 'simulados', "
        "'flashcards', 'estatisticas', 'dashboard_completo', 'ai_explicacao_questao', "
        "'ai_resumos', 'ai_cronograma', 'ai_analise_desempenho', 'analytics_avancado'"
        ")"
    )