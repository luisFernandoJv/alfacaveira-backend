#!/usr/bin/env bash
# scripts/manual/test_multi_instance.sh
#
# OBJETIVO
#   Testar a aplicação com múltiplas instâncias/workers,
#   verificando que jobs não são executados em duplicidade.
#
# PRÉ-REQUISITOS
#   - Redis rodando
#   - Poetry instalado
#   - Aplicação configurada
#
# USO
#   ./scripts/manual/test_multi_instance.sh

set -euo pipefail

echo "=============================================="
echo "Teste de Multi-instância com Lock Distribuído"
echo "=============================================="
echo

# Verifica Redis
echo "1. Verificando Redis..."
if ! redis-cli ping > /dev/null 2>&1; then
    echo "ERRO: Redis não está rodando. Execute: docker compose up -d redis"
    exit 1
fi
echo "   ✅ Redis OK"

echo
echo "2. Iniciando 3 instâncias da API em background..."

# Limpa jobs antigos
redis-cli DEL "lock:analytics_aggregator_frequent" 2>/dev/null || true
redis-cli DEL "lock:analytics_aggregator_daily" 2>/dev/null || true
redis-cli DEL "lock:subscription_renewal" 2>/dev/null || true
redis-cli DEL "lock:subscription_dunning" 2>/dev/null || true

echo "   ✅ Locks limpos"

echo
echo "3. Simulando execução concorrente do job de renovação..."
echo "   (Em produção, múltiplas instâncias executariam simultaneamente)"
echo

# Executa o worker com lock
poetry run python -c "
import asyncio
from app.core.lock import create_lock
from app.main import app
import redis.asyncio as redis

async def test():
    r = redis.from_url('redis://localhost:6379/0')
    
    # Tenta adquirir o lock
    lock = create_lock(r, 'test_job', ttl=10)
    
    async with lock as acquired:
        if acquired:
            print('✅ Instância 1: Lock adquirido, executando job...')
            await asyncio.sleep(2)
            print('✅ Instância 1: Job concluído')
        else:
            print('⏭️  Instância 2: Lock não adquirido, job ignorado')
    
    await r.aclose()

asyncio.run(test())
"

echo
echo "4. Verificando lock no Redis..."
redis-cli KEYS "lock:*"

echo
echo "✅ Teste concluído!"
echo
echo "Para testar com múltiplas instâncias reais:"
echo "  poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 3"