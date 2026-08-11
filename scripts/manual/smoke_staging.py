#!/usr/bin/env python
"""Smoke test para staging (PROMPT 20).

Verifica:
1. Health check (/health)
2. Autenticação (login)
3. Listagem de planos (/plans)
4. Listagem de questões (/questions)
5. Métricas (/metrics)
"""

import asyncio
import httpx
import os
import sys

BASE_URL = os.environ.get("STAGING_URL", "http://localhost:8000")
API_URL = f"{BASE_URL}/api/v1"

# Credenciais de teste (nunca usar em produção!)
TEST_USER = os.environ.get("TEST_USER", "admin@focopolicial.com.br")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "Admin@123456")


async def test_health():
    """Testa endpoint /health."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
        assert response.status_code == 200, f"Health check falhou: {response.status_code}"
        data = response.json()
        assert data.get("status") == "ok", "Health check retornou status inválido"
        print("✅ /health OK")


async def test_auth():
    """Testa autenticação."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_URL}/auth/login",
            json={"email": TEST_USER, "password": TEST_PASSWORD},
        )
        assert response.status_code == 200, f"Login falhou: {response.status_code}"
        data = response.json()
        assert "data" in data, "Resposta sem data"
        token = data["data"].get("access_token")
        assert token, "Token não retornado"
        print("✅ /auth/login OK")
        return token


async def test_plans(token: str):
    """Testa listagem de planos."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_URL}/billing/plans",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, f"Planos falhou: {response.status_code}"
        data = response.json()
        assert "data" in data, "Resposta sem data"
        plans = data["data"]
        assert len(plans) >= 3, f"Esperados pelo menos 3 planos, recebidos {len(plans)}"
        print(f"✅ /billing/plans OK ({len(plans)} planos)")


async def test_questions(token: str):
    """Testa listagem de questões."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_URL}/questions?limit=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, f"Questões falhou: {response.status_code}"
        data = response.json()
        assert "data" in data, "Resposta sem data"
        print("✅ /questions OK")


async def test_metrics():
    """Testa endpoint /metrics."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200, f"Métricas falhou: {response.status_code}"
        content = response.text
        assert "http_requests_total" in content, "Métrica http_requests_total não encontrada"
        assert "python_info" in content, "Métrica python_info não encontrada"
        print("✅ /metrics OK")


async def run_smoke():
    """Executa todos os testes."""
    print(f"\n🚀 Smoke Test - Staging ({BASE_URL})")
    print("=" * 50)

    try:
        await test_health()
        token = await test_auth()
        await test_plans(token)
        await test_questions(token)
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