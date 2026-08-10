"""Teste unitário do worker `app.workers.subscription_dunning` (PROMPT 11).

Mesmo espírito de `test_subscription_renewal_worker.py` (PROMPT 10): sem
banco real, dublês compartilhados via monkeypatch, exercitando `run_once`
fim-a-fim (job -> `PaymentService` -> `SubscriptionService`).

Critérios de aceite do PROMPT 11 cobertos aqui:
- retry de recobrança só para assinaturas INADIMPLENTE com tentativa
  elegível (`dunning_next_retry_at <= now`, `dunning_attempts < max`);
- recobrança aprovada -> ATIVA, período avançado, `dunning_*` limpos;
- recobrança recusada -> permanece INADIMPLENTE, `dunning_attempts`
  incrementado, novo `dunning_next_retry_at` agendado (ou não, se
  esgotado);
- grace period vencido -> EXPIRADA, independentemente de tentativas
  restantes;
- rodar o job duas vezes seguidas não duplica cobrança nem histórico.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.models.enums import (
    BillingPeriod,
    PaymentStatus,
    SubscriptionHistoryReason,
    SubscriptionStatus,
)
from app.services.billing import gateway as gateway_module
from app.services.billing import payment_service as payment_service_module
from app.services.billing import subscription_service as subscription_service_module
from app.workers import subscription_dunning as subscription_dunning_module
from app.workers.subscription_dunning import run_once
from tests.unit.billing.factories import make_plan, make_subscription
from tests.unit.billing.fakes import (
    FakeAsyncSession,
    FakePaymentRepository,
    FakePlanRepository,
    FakeSubscriptionHistoryRepository,
    FakeSubscriptionRepository,
)


class FakeApprovingGateway:
    """Sempre aprova, síncrono — mesmo comportamento do driver `console`
    real (ver `gateway.py`), mas sem passar pelo `structlog`/settings."""

    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    async def charge(self, *, amount_cents: int, currency: str, subscription_id: uuid.UUID):
        self.calls.append(subscription_id)
        return gateway_module.ChargeResult(
            provider="fake",
            provider_payment_id=str(uuid.uuid4()),
            status=PaymentStatus.APROVADO,
        )

    async def parse_webhook_event(self, *, raw_body: bytes, headers):
        raise NotImplementedError


class FakeDecliningGateway:
    """Sempre recusa, síncrono — usado para exercitar o caminho de
    retry-falhou do worker de dunning."""

    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    async def charge(self, *, amount_cents: int, currency: str, subscription_id: uuid.UUID):
        self.calls.append(subscription_id)
        return gateway_module.ChargeResult(
            provider="fake",
            provider_payment_id=str(uuid.uuid4()),
            status=PaymentStatus.RECUSADO,
        )

    async def parse_webhook_event(self, *, raw_body: bytes, headers):
        raise NotImplementedError


def _wire(monkeypatch: pytest.MonkeyPatch, gateway):
    subs = FakeSubscriptionRepository()
    plans = FakePlanRepository()
    payments = FakePaymentRepository()

    monkeypatch.setattr(subscription_dunning_module, "SubscriptionRepository", lambda session: subs)
    monkeypatch.setattr(payment_service_module, "PaymentRepository", lambda session: payments)
    monkeypatch.setattr(payment_service_module, "SubscriptionRepository", lambda session: subs)
    monkeypatch.setattr(payment_service_module, "get_payment_gateway", lambda: gateway)
    monkeypatch.setattr(subscription_service_module, "SubscriptionRepository", lambda session: subs)
    monkeypatch.setattr(subscription_service_module, "PlanRepository", lambda session: plans)
    monkeypatch.setattr(
        subscription_service_module,
        "SubscriptionHistoryRepository",
        FakeSubscriptionHistoryRepository,
    )
    return subs, plans, payments


@pytest.fixture
def repos_approving(monkeypatch: pytest.MonkeyPatch):
    gateway = FakeApprovingGateway()
    subs, plans, payments = _wire(monkeypatch, gateway)
    return subs, plans, payments, gateway


@pytest.fixture
def repos_declining(monkeypatch: pytest.MonkeyPatch):
    gateway = FakeDecliningGateway()
    subs, plans, payments = _wire(monkeypatch, gateway)
    return subs, plans, payments, gateway


class TestDunningRetryRecovers:
    async def test_charges_and_recovers_an_eligible_subscription(self, repos_approving):
        subs, plans, payments, gateway = repos_approving
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            dunning_attempts=1,
            dunning_next_retry_at=now - timedelta(hours=1),  # elegível
            dunning_grace_period_ends_at=now + timedelta(days=1),  # ainda não venceu
        )
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        assert result == {"retried": 1, "recovered": 1, "expired": 0}
        assert len(gateway.calls) == 1
        assert subs.store[sub.id].status == SubscriptionStatus.ATIVA
        assert subs.store[sub.id].dunning_attempts == 0
        assert subs.store[sub.id].dunning_next_retry_at is None
        recovery_entries = [
            e
            for e in session.added
            if getattr(e, "reason", None) == SubscriptionHistoryReason.RECUPERADA_DUNNING
        ]
        assert len(recovery_entries) == 1

    async def test_does_not_select_subscription_not_yet_eligible(self, repos_approving):
        subs, plans, payments, gateway = repos_approving
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            dunning_attempts=1,
            dunning_next_retry_at=now + timedelta(hours=1),  # ainda não chegou a vez
            dunning_grace_period_ends_at=now + timedelta(days=1),
        )
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        assert result == {"retried": 0, "recovered": 0, "expired": 0}
        assert len(gateway.calls) == 0

    async def test_does_not_select_subscription_with_attempts_exhausted(self, repos_approving):
        subs, plans, payments, gateway = repos_approving
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            dunning_attempts=settings.DUNNING_MAX_RETRIES,  # já esgotado
            dunning_next_retry_at=now - timedelta(hours=1),
            dunning_grace_period_ends_at=now + timedelta(days=1),
        )
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        assert result == {"retried": 0, "recovered": 0, "expired": 0}
        assert len(gateway.calls) == 0


class TestDunningRetryFails:
    async def test_declined_retry_increments_attempts_and_stays_inadimplente(
        self, repos_declining
    ):
        subs, plans, payments, gateway = repos_declining
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            dunning_attempts=0,
            dunning_next_retry_at=now - timedelta(hours=1),
            dunning_grace_period_ends_at=now + timedelta(days=3),
        )
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        assert result == {"retried": 1, "recovered": 0, "expired": 0}
        assert subs.store[sub.id].status == SubscriptionStatus.INADIMPLENTE
        assert subs.store[sub.id].dunning_attempts == 1
        assert subs.store[sub.id].dunning_next_retry_at is not None
        retry_failed_entries = [
            e
            for e in session.added
            if getattr(e, "reason", None) == SubscriptionHistoryReason.RETRY_DUNNING_FALHOU
        ]
        assert len(retry_failed_entries) == 1

    async def test_running_the_job_twice_does_not_duplicate_the_charge(self, repos_declining):
        """Critério de aceite do PROMPT 11 (mesmo espírito do PROMPT 10):
        rodar o job duas vezes seguidas sobre o mesmo estado não cobra em
        duplicidade — depois da primeira falha, `dunning_next_retry_at` foi
        reagendado para o futuro, então a segunda execução (mesmo `now`) não
        encontra mais a assinatura elegível."""
        subs, plans, payments, gateway = repos_declining
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            dunning_attempts=0,
            dunning_next_retry_at=now - timedelta(hours=1),
            dunning_grace_period_ends_at=now + timedelta(days=3),
        )
        subs.seed(sub)
        session = FakeAsyncSession()

        first = await run_once(session, now=now)
        second = await run_once(session, now=now)

        assert first == {"retried": 1, "recovered": 0, "expired": 0}
        assert second == {"retried": 0, "recovered": 0, "expired": 0}
        assert len(gateway.calls) == 1
        assert len(payments.store) == 1
        assert subs.store[sub.id].dunning_attempts == 1


class TestDunningExpiration:
    async def test_expires_subscription_past_grace_period(self, repos_approving):
        subs, plans, payments, gateway = repos_approving
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            dunning_attempts=settings.DUNNING_MAX_RETRIES,
            dunning_next_retry_at=None,  # tentativas já esgotadas
            dunning_grace_period_ends_at=now - timedelta(hours=1),  # grace period vencido
        )
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        assert result == {"retried": 0, "recovered": 0, "expired": 1}
        assert len(gateway.calls) == 0  # não tenta cobrar de novo
        assert subs.store[sub.id].status == SubscriptionStatus.EXPIRADA

    async def test_running_the_job_twice_does_not_duplicate_expiration_history(
        self, repos_approving
    ):
        subs, plans, payments, gateway = repos_approving
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            dunning_attempts=settings.DUNNING_MAX_RETRIES,
            dunning_next_retry_at=None,
            dunning_grace_period_ends_at=now - timedelta(hours=1),
        )
        subs.seed(sub)
        session = FakeAsyncSession()

        first = await run_once(session, now=now)
        second = await run_once(session, now=now)

        assert first == {"retried": 0, "recovered": 0, "expired": 1}
        # Segunda execução: a assinatura já está EXPIRADA, então
        # `list_due_for_dunning_expiration` (filtra status == INADIMPLENTE)
        # não a seleciona mais.
        assert second == {"retried": 0, "recovered": 0, "expired": 0}
        expiration_entries = [
            e
            for e in session.added
            if getattr(e, "reason", None) == SubscriptionHistoryReason.EXPIRADA
        ]
        assert len(expiration_entries) == 1

    async def test_expires_even_with_retry_attempts_still_remaining(self, repos_approving):
        """Requisito explícito do PROMPT 11: o grace period governa a
        expiração, independentemente de quantas tentativas de retry ainda
        restariam — uma assinatura com grace period vencido expira mesmo
        que `dunning_attempts < DUNNING_MAX_RETRIES`."""
        subs, plans, payments, gateway = repos_approving
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            dunning_attempts=1,  # ainda restariam tentativas
            dunning_next_retry_at=now + timedelta(days=5),  # próximo retry no futuro distante
            dunning_grace_period_ends_at=now - timedelta(hours=1),  # mas grace period já venceu
        )
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        assert result == {"retried": 0, "recovered": 0, "expired": 1}
        assert subs.store[sub.id].status == SubscriptionStatus.EXPIRADA