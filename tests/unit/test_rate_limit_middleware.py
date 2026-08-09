"""Testes isolados do RateLimitMiddleware (PROMPT 03).

Não dependem de um Redis real nem dos fixtures de `tests/conftest.py`
(ainda placeholder) — usam um double em memória para simular o cliente
Redis, incluindo o caso de falha. Mesma filosofia dos testes de
`test_billing_gateway_config.py` (PROMPT 02): rodam isolados, cobrindo só
o componente da tarefa.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import settings
from app.middlewares.rate_limit import RateLimitMiddleware, _resolve_policy


class FakeRedis:
    """INCR/EXPIRE em memória — suficiente para exercitar a lógica de
    janela fixa por chave sem precisar de um Redis real."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:  # noqa: ARG002
        return None


class FailingRedis:
    """Simula o Redis fora do ar: qualquer operação levanta."""

    async def incr(self, key: str) -> int:  # noqa: ARG002
        raise ConnectionError("redis unreachable")

    async def expire(self, key: str, seconds: int) -> None:  # noqa: ARG002
        raise ConnectionError("redis unreachable")


def _build_app(redis_client: object | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
    app.state.redis = redis_client

    @app.get("/api/v1/questions")
    async def questions() -> dict[str, str]:
        return {"ok": "default-route"}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, str]:
        return {"ok": "login"}

    @app.post("/api/v1/auth/register")
    async def register() -> dict[str, str]:
        return {"ok": "register"}

    @app.post("/api/v1/auth/forgot-password")
    async def forgot_password() -> dict[str, str]:
        return {"ok": "forgot-password"}

    @app.post("/api/v1/billing/webhooks/payments")
    async def billing_webhook() -> dict[str, str]:
        return {"ok": "billing"}

    return app


async def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _restore_settings():
    """`settings` é um singleton mutável — evita vazar overrides entre
    testes."""
    original = {
        "RATE_LIMIT_PER_MINUTE": settings.RATE_LIMIT_PER_MINUTE,
        "RATE_LIMIT_LOGIN_PER_MINUTE": settings.RATE_LIMIT_LOGIN_PER_MINUTE,
        "RATE_LIMIT_REGISTER_PER_MINUTE": settings.RATE_LIMIT_REGISTER_PER_MINUTE,
        "RATE_LIMIT_FORGOT_PASSWORD_PER_MINUTE": settings.RATE_LIMIT_FORGOT_PASSWORD_PER_MINUTE,
        "RATE_LIMIT_BILLING_PER_MINUTE": settings.RATE_LIMIT_BILLING_PER_MINUTE,
        "RATE_LIMIT_FAIL_OPEN": settings.RATE_LIMIT_FAIL_OPEN,
    }
    yield
    for key, value in original.items():
        setattr(settings, key, value)


def test_resolve_policy_maps_known_prefixes() -> None:
    assert _resolve_policy("/api/v1/auth/login").name == "login"
    assert _resolve_policy("/api/v1/auth/register").name == "register"
    assert _resolve_policy("/api/v1/auth/forgot-password").name == "forgot_password"
    assert _resolve_policy("/api/v1/auth/reset-password").name == "reset_password"
    assert _resolve_policy("/api/v1/billing/webhooks/payments").name == "billing"


def test_resolve_policy_falls_back_to_default_for_unknown_route() -> None:
    policy = _resolve_policy("/api/v1/questions")
    assert policy.name == "default"
    assert policy.limit_per_minute == settings.RATE_LIMIT_PER_MINUTE


def test_login_policy_is_stricter_than_default_and_enforced() -> None:
    settings.RATE_LIMIT_LOGIN_PER_MINUTE = 2
    settings.RATE_LIMIT_PER_MINUTE = 60

    async def run() -> list[int]:
        app = _build_app(FakeRedis())
        async with await _client(app) as client:
            statuses = []
            for _ in range(3):
                resp = await client.post("/api/v1/auth/login")
                statuses.append(resp.status_code)
            return statuses

    statuses = asyncio.run(run())
    assert statuses == [200, 200, 429]


def test_rate_limited_response_uses_error_envelope() -> None:
    settings.RATE_LIMIT_LOGIN_PER_MINUTE = 1

    async def run() -> httpx.Response:
        app = _build_app(FakeRedis())
        async with await _client(app) as client:
            await client.post("/api/v1/auth/login")
            return await client.post("/api/v1/auth/login")

    resp = asyncio.run(run())
    assert resp.status_code == 429
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "rate_limited"


def test_policies_have_independent_counters() -> None:
    """Esgotar o limite de login não deve afetar register nem a rota
    default — cada política tem seu próprio balde."""
    settings.RATE_LIMIT_LOGIN_PER_MINUTE = 1
    settings.RATE_LIMIT_REGISTER_PER_MINUTE = 5
    settings.RATE_LIMIT_PER_MINUTE = 5

    async def run() -> tuple[int, int, int, int]:
        app = _build_app(FakeRedis())
        async with await _client(app) as client:
            login_1 = (await client.post("/api/v1/auth/login")).status_code
            login_2 = (await client.post("/api/v1/auth/login")).status_code
            register_1 = (await client.post("/api/v1/auth/register")).status_code
            default_1 = (await client.get("/api/v1/questions")).status_code
            return login_1, login_2, register_1, default_1

    login_1, login_2, register_1, default_1 = asyncio.run(run())
    assert login_1 == 200
    assert login_2 == 429  # login já esgotado
    assert register_1 == 200  # política separada, não afetada
    assert default_1 == 200  # política separada, não afetada


def test_billing_policy_is_enforced_independently() -> None:
    settings.RATE_LIMIT_BILLING_PER_MINUTE = 1

    async def run() -> tuple[int, int]:
        app = _build_app(FakeRedis())
        async with await _client(app) as client:
            first = (await client.post("/api/v1/billing/webhooks/payments")).status_code
            second = (await client.post("/api/v1/billing/webhooks/payments")).status_code
            return first, second

    first, second = asyncio.run(run())
    assert first == 200
    assert second == 429


def test_redis_missing_fails_open_by_default_and_request_succeeds() -> None:
    settings.RATE_LIMIT_FAIL_OPEN = True

    async def run() -> int:
        app = _build_app(None)  # request.app.state.redis nunca foi setado
        async with await _client(app) as client:
            resp = await client.post("/api/v1/auth/login")
            return resp.status_code

    assert asyncio.run(run()) == 200


def test_redis_missing_fails_closed_when_configured() -> None:
    settings.RATE_LIMIT_FAIL_OPEN = False

    async def run() -> int:
        app = _build_app(None)
        async with await _client(app) as client:
            resp = await client.post("/api/v1/auth/login")
            return resp.status_code

    assert asyncio.run(run()) == 503


def test_redis_error_mid_request_fails_open_by_default() -> None:
    settings.RATE_LIMIT_FAIL_OPEN = True

    async def run() -> int:
        app = _build_app(FailingRedis())
        async with await _client(app) as client:
            resp = await client.post("/api/v1/auth/login")
            return resp.status_code

    assert asyncio.run(run()) == 200


def test_redis_error_mid_request_fails_closed_when_configured() -> None:
    settings.RATE_LIMIT_FAIL_OPEN = False

    async def run() -> int:
        app = _build_app(FailingRedis())
        async with await _client(app) as client:
            resp = await client.post("/api/v1/auth/login")
            return resp.status_code

    assert asyncio.run(run()) == 503


def test_unrelated_route_unaffected_by_login_lockout() -> None:
    settings.RATE_LIMIT_LOGIN_PER_MINUTE = 1
    settings.RATE_LIMIT_PER_MINUTE = 60

    async def run() -> tuple[int, int, int]:
        app = _build_app(FakeRedis())
        async with await _client(app) as client:
            await client.post("/api/v1/auth/login")
            locked = (await client.post("/api/v1/auth/login")).status_code
            still_ok = (await client.get("/api/v1/questions")).status_code
            return locked, still_ok, 0

    locked, still_ok, _ = asyncio.run(run())
    assert locked == 429
    assert still_ok == 200