#!/usr/bin/env bash
# scripts/manual/test_subscription_upgrade_downgrade_staging.sh
#
# OBJETIVO
#   Exercitar app/services/billing/subscription_service.py (PROMPT 12,
#   roadmap item 12 — Upgrade, Downgrade e Pró-rata) fim-a-fim contra um
#   Postgres de staging real.
#
# PRÉ-REQUISITOS
#   - Banco de staging acessível via DATABASE_URL
#   - Migrations em dia (00010_upgrade_downgrade_prorata)
#   - PAYMENT_GATEWAY_DRIVER=console (padrão)
#   - Poetry instalado
#
# USO
#   ./scripts/manual/test_subscription_upgrade_downgrade_staging.sh
#
#   Ou, para execução automática:
#   poetry run python scripts/manual/test_subscription_upgrade_downgrade_staging.py
#

set -euo pipefail

echo "================================================"
echo "Script de validação de Upgrade/Downgrade/Pró-rata"
echo "================================================"
echo
echo "PRÉ-REQUISITOS:"
echo "  1. Banco de staging configurado em DATABASE_URL"
echo "  2. Migrations aplicadas (00010_upgrade_downgrade_prorata)"
echo "  3. Dados seedados (scripts/seed_test_data.py)"
echo "  4. API rodando (uvicorn app.main:app)"
echo
echo "Este script é um roteiro. Execute os passos manualmente."
echo
echo "Para execução assistida, use o script Python:"
echo "  poetry run python scripts/manual/test_subscription_upgrade_downgrade_staging.py"
echo

exit 0