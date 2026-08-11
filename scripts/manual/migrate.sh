#!/usr/bin/env bash
# scripts/manual/migrate.sh
#
# OBJETIVO
#   Aplica migrations com backup automático e verificação.
#
# USO
#   ./scripts/manual/migrate.sh [staging|production]
#
# EXEMPLO
#   ./scripts/manual/migrate.sh staging

set -euo pipefail

ENVIRONMENT=${1:-staging}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="/tmp/backup_${ENVIRONMENT}_${TIMESTAMP}.sql"

echo "=============================================="
echo "Migration - ${ENVIRONMENT}"
echo "=============================================="
echo

if [[ "$ENVIRONMENT" != "staging" && "$ENVIRONMENT" != "production" ]]; then
    echo "ERRO: Ambiente inválido. Use staging ou production."
    exit 1
fi

# Verifica se há migrations pendentes
echo "1. Verificando migrations pendentes..."
PENDING=$(poetry run alembic current | grep -c "(head)")
if [[ "$PENDING" -eq 1 ]]; then
    echo "   ✅ Nenhuma migration pendente"
    exit 0
fi
echo "   ⚠️  Migrations pendentes encontradas"

# Backups
echo "2. Criando backup do banco..."
PGPASSWORD=postgres pg_dump -h localhost -U postgres foco_policial > "$BACKUP_FILE"
echo "   ✅ Backup criado: $BACKUP_FILE"

# Mostra migrations
echo "3. Migrations a serem aplicadas:"
poetry run alembic history --verbose | head -10

# Confirmação
echo
echo "⚠️  ATENÇÃO: As migrations acima serão aplicadas em ${ENVIRONMENT}."
read -p "   Continuar? (s/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Ss]$ ]]; then
    echo "   ❌ Cancelado"
    exit 0
fi

# Aplica migrations
echo "4. Aplicando migrations..."
poetry run alembic upgrade head
echo "   ✅ Migrations aplicadas"

# Verifica
echo "5. Verificando..."
poetry run alembic current
echo "   ✅ Verificação concluída"

echo
echo "=============================================="
echo "✅ Migration concluída com sucesso!"
echo "   Backup: $BACKUP_FILE"
echo "=============================================="