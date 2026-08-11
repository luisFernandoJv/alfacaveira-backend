#!/usr/bin/env python
"""Smoke test para produção (PROMPT 20).

Versão mais leve que o staging, apenas valida serviços essenciais.
"""

import asyncio
import httpx
import os
import sys

BASE_URL = os.environ.get("PRODUCTION_URL", "https://focopolicial.com.br")


async def test_health():
    """Testa endpoint /health."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
        assert response.status_code == 200, f"Health check falhou: {response.status_code}"
        data = response.json()
        assert data.get("status") == "ok", "Health check retornou status inválido"
        print("✅ /health OK")


async def test_metrics():
    """Testa endpoint /metrics."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200, f"Métricas falhou: {response.status_code}"
        print("✅ /metrics OK")


async def run_smoke():
    """Executa todos os testes."""
    print(f"\n🚀 Smoke Test - Production ({BASE_URL})")
    print("=" * 50)

    try:
        await test_health()
        await test_metrics()

        print("\n" + "=" * 50)
        print("✅ TODOS OS TESTES PASSARAM!")
        return 0
    except AssertionError as e:
        print(f"\n❌ TESTE FALHOU: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERRO INESPERADO: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_smoke()))