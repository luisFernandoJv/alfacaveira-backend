# tests/unit/billing/test_subscription_renewal_worker_with_reminder.py
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.models.enums import BillingPeriod, PaymentStatus, SubscriptionStatus
from app.models.identity.user import User
from app.workers import subscription_renewal as subscription_renewal_module
from app.workers.subscription_renewal import run_once
from tests.unit.billing.factories import make_plan, make_subscription
from tests.unit.billing.fakes import (
    FakeAsyncSession,
    FakePaymentRepository,
    FakePlanRepository,
    FakeSubscriptionHistoryRepository,
    FakeSubscriptionRepository,
    FakeUserRepository,
)


class TestSubscriptionRenewalWorkerWithReminder:
    """Testes do worker de renovação com lembrete (PROMPT 13)."""

    @pytest.fixture
    def repos(self, monkeypatch):
        subs = FakeSubscriptionRepository()
        plans = FakePlanRepository()
        payments = FakePaymentRepository()
        users = FakeUserRepository()

        # Substituir repositórios nos módulos
        monkeypatch.setattr(subscription_renewal_module, "SubscriptionRepository", lambda session: subs)
        monkeypatch.setattr(
            subscription_renewal_module, "UserRepository", lambda session: users
        )

        from app.services.billing import payment_service as payment_service_module
        from app.services.billing import subscription_service as subscription_service_module

        monkeypatch.setattr(payment_service_module, "PaymentRepository", lambda session: payments)
        monkeypatch.setattr(payment_service_module, "SubscriptionRepository", lambda session: subs)
        monkeypatch.setattr(subscription_service_module, "SubscriptionRepository", lambda session: subs)
        monkeypatch.setattr(subscription_service_module, "PlanRepository", lambda session: plans)
        monkeypatch.setattr(
            subscription_service_module,
            "SubscriptionHistoryRepository",
            FakeSubscriptionHistoryRepository,
        )

        return subs, plans, payments, users

    @pytest.mark.asyncio
    async def test_sends_renewal_reminder_for_eligible_subscription(self, repos, monkeypatch):
        """Testa que o worker envia lembrete para assinatura elegível."""
        subs, plans, payments, users = repos
        monkeypatch.setattr(settings, "NOTIFY_RENEWAL_REMINDER", True)
        monkeypatch.setattr(settings, "RENEWAL_REMINDER_DAYS_BEFORE", 3)

        # Criar plano e assinatura
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)

        # Criar usuário REAL (não FakeUserRepository)
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email="teste-reminder@teste.com",
            full_name="Usuário Teste Reminder",
            is_active=True,
        )
        users.seed(user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=user_id,
        )
        # Vence em exatamente 3 dias
        sub.current_period_end = now + timedelta(days=3)
        sub.renewal_reminder_sent_at = None
        subs.seed(sub)

        session = FakeAsyncSession()

        # Executar o worker
        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_renewal_reminder",
            new_callable=AsyncMock,
        ) as mock_notify:
            result = await run_once(session, now=now)

            # Verificar que o lembrete foi enviado
            mock_notify.assert_called_once()
            assert result["reminders_sent"] == 1

        # Verificar que a assinatura foi marcada como enviada
        updated_sub = subs.store[sub.id]
        assert updated_sub.renewal_reminder_sent_at is not None

    @pytest.mark.asyncio
    async def test_does_not_send_reminder_if_already_sent(self, repos, monkeypatch):
        """Testa que lembrete não é enviado se já foi enviado antes."""
        subs, plans, payments, users = repos
        monkeypatch.setattr(settings, "NOTIFY_RENEWAL_REMINDER", True)

        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)

        # Criar usuário REAL
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email="teste-already-sent@teste.com",
            full_name="Usuário Teste Already Sent",
            is_active=True,
        )
        users.seed(user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=user_id,
        )
        sub.current_period_end = now + timedelta(days=3)
        sub.renewal_reminder_sent_at = now  # Já enviado
        subs.seed(sub)

        session = FakeAsyncSession()

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_renewal_reminder",
            new_callable=AsyncMock,
        ) as mock_notify:
            result = await run_once(session, now=now)
            mock_notify.assert_not_called()
            assert result["reminders_sent"] == 0

    @pytest.mark.asyncio
    async def test_does_not_send_reminder_if_disabled(self, repos, monkeypatch):
        """Testa que lembrete não é enviado se desabilitado."""
        subs, plans, payments, users = repos
        monkeypatch.setattr(settings, "NOTIFY_RENEWAL_REMINDER", False)

        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)

        # Criar usuário REAL
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email="teste-disabled@teste.com",
            full_name="Usuário Teste Disabled",
            is_active=True,
        )
        users.seed(user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=user_id,
        )
        sub.current_period_end = now + timedelta(days=3)
        sub.renewal_reminder_sent_at = None
        subs.seed(sub)

        session = FakeAsyncSession()

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_renewal_reminder",
            new_callable=AsyncMock,
        ) as mock_notify:
            result = await run_once(session, now=now)
            mock_notify.assert_not_called()
            assert result["reminders_sent"] == 0

    @pytest.mark.asyncio
    async def test_reminder_failure_does_not_block_other_operations(self, repos, monkeypatch):
        """Testa que falha no envio de lembrete não bloqueia outras operações."""
        subs, plans, payments, users = repos
        monkeypatch.setattr(settings, "NOTIFY_RENEWAL_REMINDER", True)

        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)
        now = datetime.now(UTC)

        # Criar usuário REAL para ambas assinaturas
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email="teste-failure@teste.com",
            full_name="Usuário Teste Failure",
            is_active=True,
        )
        users.seed(user)

        # Criar duas assinaturas: uma com lembrete, uma para cobrança
        sub1 = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=user_id,
        )
        sub1.current_period_end = now + timedelta(days=3)  # Para lembrete
        sub1.renewal_reminder_sent_at = None
        subs.seed(sub1)

        sub2 = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=user_id,
        )
        sub2.current_period_end = now - timedelta(hours=1)  # Vencida para cobrança
        sub2.cancel_at_period_end = False
        subs.seed(sub2)

        session = FakeAsyncSession()

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_renewal_reminder",
            new_callable=AsyncMock,
            side_effect=Exception("Falha no envio do e-mail"),
        ):
            # Deve processar a cobrança mesmo com falha no lembrete
            result = await run_once(session, now=now)
            assert result["reminders_sent"] == 0
            # A cobrança ainda deve ser processada (sub2 está vencida)
            # Nota: o resultado pode variar dependendo do estado do gateway
            # No fake, a cobrança é aprovada
            assert result["charged"] >= 1