"""Teste unitário do worker `app.workers.subscription_renewal` (PROMPT 10).

Critério de aceite explícito do PROMPT 10 ("TESTES AUTO: Executar job duas
vezes não duplica cobrança") é validado aqui chamando `run_once` duas vezes
seguidas sobre o mesmo estado em memória — sem banco real, mesmo espírito
dos demais testes de billing (`tests/unit/billing/fakes.py`).

`run_once` resolve `SubscriptionRepository`/`PaymentService`/
`SubscriptionService` a partir dos namespaces de módulo de
`app.workers.subscription_renewal`, `app.services.billing.payment_service` e
`app.services.billing.subscription_service` — o fixture `repos` abaixo
substitui os três pelos mesmos dublês compartilhados (mesma técnica de
`test_payment_service.py`), incluindo o gateway (via
`payment_service_module.get_payment_gateway`), para que o job inteiro rode
fim-a-fim sem I/O real.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import (
    BillingPeriod,
    PaymentStatus,
    SubscriptionHistoryReason,
    SubscriptionStatus,
)
from app.services.billing import gateway as gateway_module
from app.services.billing import payment_service as payment_service_module
from app.services.billing import subscription_service as subscription_service_module
from app.workers import subscription_renewal as subscription_renewal_module
from app.workers.subscription_renewal import run_once
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


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch):
    subs = FakeSubscriptionRepository()
    plans = FakePlanRepository()
    payments = FakePaymentRepository()
    gateway = FakeApprovingGateway()

    monkeypatch.setattr(subscription_renewal_module, "SubscriptionRepository", lambda session: subs)
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
    return subs, plans, payments, gateway


class TestRunOnceRenewsDueSubscriptions:
    async def test_charges_and_renews_a_due_subscription(self, repos):
        subs, plans, payments, gateway = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan)
        sub.current_period_end = now - timedelta(hours=1)  # vencida
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        # CORRIGIDO: adicionar reminders_sent: 0
        assert result == {
            "charged": 1,
            "finalized_cancellations": 0,
            "downgrades_applied": 0,
            "reminders_sent": 0,
        }
        assert len(gateway.calls) == 1
        assert subs.store[sub.id].status == SubscriptionStatus.ATIVA
        assert subs.store[sub.id].current_period_end > now
        renewal_entries = [
            e
            for e in session.added
            if getattr(e, "reason", None) == SubscriptionHistoryReason.RENOVADA
        ]
        assert len(renewal_entries) == 1

    async def test_running_the_job_twice_does_not_duplicate_the_charge(self, repos):
        """Critério de aceite do PROMPT 10: rodar o job duas vezes seguidas
        sobre o mesmo estado não cobra nem renova em duplicidade — a
        segunda execução não encontra mais a assinatura em
        `list_due_for_renewal` porque a primeira já avançou
        `current_period_end` para o futuro."""
        subs, plans, payments, gateway = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan)
        sub.current_period_end = now - timedelta(hours=1)
        subs.seed(sub)
        session = FakeAsyncSession()

        first = await run_once(session, now=now)
        period_after_first_run = subs.store[sub.id].current_period_end
        second = await run_once(session, now=now)

        # CORRIGIDO: adicionar reminders_sent: 0 em ambas as asserções
        assert first == {
            "charged": 1,
            "finalized_cancellations": 0,
            "downgrades_applied": 0,
            "reminders_sent": 0,
        }
        assert second == {
            "charged": 0,
            "finalized_cancellations": 0,
            "downgrades_applied": 0,
            "reminders_sent": 0,
        }
        assert len(gateway.calls) == 1
        assert len(payments.store) == 1
        assert subs.store[sub.id].current_period_end == period_after_first_run
        renewal_entries = [
            e
            for e in session.added
            if getattr(e, "reason", None) == SubscriptionHistoryReason.RENOVADA
        ]
        assert len(renewal_entries) == 1

    async def test_does_not_select_subscriptions_not_yet_due(self, repos):
        subs, plans, payments, gateway = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan)
        sub.current_period_end = now + timedelta(days=5)  # ainda não venceu
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        # CORRIGIDO: adicionar reminders_sent: 0
        assert result == {
            "charged": 0,
            "finalized_cancellations": 0,
            "downgrades_applied": 0,
            "reminders_sent": 0,
        }
        assert len(gateway.calls) == 0

    async def test_does_not_charge_subscription_scheduled_for_cancellation(self, repos):
        """Requisito do PROMPT 10 ('não cobrar cancelada/expirada'), caso
        limítrofe: uma assinatura ATIVA com `cancel_at_period_end=True`
        cujo período venceu não deve ser cobrada — deve ser finalizada
        como cancelamento, não renovada."""
        subs, plans, payments, gateway = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.ATIVA, plan=plan, cancel_at_period_end=True
        )
        sub.current_period_end = now - timedelta(hours=1)
        subs.seed(sub)
        session = FakeAsyncSession()

        result = await run_once(session, now=now)

        # CORRIGIDO: adicionar reminders_sent: 0
        assert result == {
            "charged": 0,
            "finalized_cancellations": 1,
            "downgrades_applied": 0,
            "reminders_sent": 0,
        }
        assert len(gateway.calls) == 0
        assert subs.store[sub.id].status == SubscriptionStatus.CANCELADA

    async def test_running_the_job_twice_does_not_duplicate_cancellation_history(self, repos):
        subs, plans, payments, gateway = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.ATIVA, plan=plan, cancel_at_period_end=True
        )
        sub.current_period_end = now - timedelta(hours=1)
        subs.seed(sub)
        session = FakeAsyncSession()

        first = await run_once(session, now=now)
        second = await run_once(session, now=now)

        # CORRIGIDO: adicionar reminders_sent: 0 em ambas as asserções
        assert first == {
            "charged": 0,
            "finalized_cancellations": 1,
            "downgrades_applied": 0,
            "reminders_sent": 0,
        }
        # Segunda execução: a assinatura já está CANCELADA, então nem
        # `list_scheduled_cancellations_due` (filtra status == ATIVA) nem
        # `list_due_for_renewal` a selecionam mais.
        assert second == {
            "charged": 0,
            "finalized_cancellations": 0,
            "downgrades_applied": 0,
            "reminders_sent": 0,
        }
        cancel_entries = [
            e
            for e in session.added
            if getattr(e, "reason", None) == SubscriptionHistoryReason.CANCELADA
        ]
        assert len(cancel_entries) == 1