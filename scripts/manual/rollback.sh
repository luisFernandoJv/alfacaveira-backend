#!/usr/bin/env bash
# scripts/manual/rollback.sh
#
# OBJETIVO
#   Realiza rollback da aplicação para a versão anterior.
#
# USO
#   ./scripts/manual/rollback.sh [staging|production]
#
# EXEMPLO
#   ./scripts/manual/rollback.sh production

set -euo pipefail

ENVIRONMENT=${1:-staging}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/tmp/rollback_${ENVIRONMENT}_${TIMESTAMP}"

echo "=============================================="
echo "Rollback - ${ENVIRONMENT}"
echo "=============================================="
echo

# Verifica ambiente
if [[ "$ENVIRONMENT" != "staging" && "$ENVIRONMENT" != "production" ]]; then
    echo "ERRO: Ambiente inválido. Use staging ou production."
    exit 1
fi

# Cria backup da configuração atual
echo "1. Criando backup da configuração atual..."
mkdir -p "$BACKUP_DIR"
cp -r .env* docker-compose.yml "$BACKUP_DIR/" 2>/dev/null || true
echo "   ✅ Backup criado em: $BACKUP_DIR"

# Identifica versão atual
echo "2. Identificando versão atual..."
CURRENT_IMAGE=$(docker images --filter "reference=*foco-policial-backend" --format "{{.Tag}}" | head -1)
if [[ -z "$CURRENT_IMAGE" ]]; then
    echo "   ⚠️  Nenhuma imagem encontrada. Usando 'latest'."
    CURRENT_IMAGE="latest"
fi
echo "   ✅ Versão atual: $CURRENT_IMAGE"

# Para o serviço
echo "3. Parando serviço..."
docker compose down
echo "   ✅ Serviço parado"

# Rollback
echo "4. Realizando rollback..."
if [[ -f "docker-compose.rollback.yml" ]]; then
    echo "   Usando docker-compose.rollback.yml"
    docker compose -f docker-compose.rollback.yml up -d
else
    echo "   ⚠️  Arquivo de rollback não encontrado. Usando configuração padrão."
    docker compose up -d
fi
echo "   ✅ Rollback aplicado"

# Health check
echo "5. Aguardando health check..."
sleep 10
if curl -f "http://localhost:8000/health" > /dev/null 2>&1; then
    echo "   ✅ Health check OK"
else
    echo "   ❌ Health check falhou!"
    echo "   🔄 Revertendo para versão anterior..."
    docker compose down
    docker compose up -d
    echo "   ✅ Reversão concluída"
    exit 1
fi

echo
echo "=============================================="
echo "✅ Rollback concluído com sucesso!"
echo "   Ambiente: $ENVIRONMENT"
echo "   Versão: $CURRENT_IMAGE"
echo "   Backup: $BACKUP_DIR"
echo "=============================================="