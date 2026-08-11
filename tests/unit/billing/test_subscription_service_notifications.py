# tests/unit/billing/test_subscription_service_notifications.py
import uuid
from datetime import UTC, datetime, timedelta  # <-- ADICIONADO timedelta
from unittest.mock import AsyncMock, MagicMock, patch  # <-- ADICIONADO MagicMock

import pytest

from app.models.identity.user import User
from app.models.enums import BillingPeriod, PaymentStatus, SubscriptionHistoryReason, SubscriptionStatus
from app.services.billing.subscription_service import SubscriptionService
from tests.unit.billing.factories import make_plan, make_subscription
from tests.unit.billing.fakes import (
    FakeAsyncSession,
    FakePlanRepository,
    FakeSubscriptionHistoryRepository,
    FakeSubscriptionRepository,
    FakeUserRepository,
)


class TestSubscriptionServiceNotifications:
    """Testes de notificações nos hooks do SubscriptionService (PROMPT 13)."""

    @pytest.fixture
    def repos(self, monkeypatch):
        subs = FakeSubscriptionRepository()
        plans = FakePlanRepository()
        users = FakeUserRepository()

        monkeypatch.setattr(
            "app.services.billing.subscription_service.SubscriptionRepository",
            lambda session: subs,
        )
        monkeypatch.setattr(
            "app.services.billing.subscription_service.PlanRepository",
            lambda session: plans,
        )
        monkeypatch.setattr(
            "app.services.billing.subscription_service.UserRepository",
            lambda session: users,
        )
        monkeypatch.setattr(
            "app.services.billing.subscription_service.SubscriptionHistoryRepository",
            FakeSubscriptionHistoryRepository,
        )

        return subs, plans, users

    @pytest.fixture
    def service(self, repos):
        return SubscriptionService(FakeAsyncSession())

    @pytest.fixture
    def test_user(self):
        """Cria um usuário de teste."""
        return User(
            id=uuid.uuid4(),
            email="teste-notificacao@teste.com",
            full_name="Usuário Teste Notificação",
            is_active=True,
        )

    @pytest.mark.asyncio
    async def test_activate_subscription_sends_notification(self, service, repos, test_user):
        """Testa que activate_subscription envia notificação de pagamento aprovado."""
        subs, plans, users = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)

        # Seed do usuário
        users.seed(test_user)

        sub = make_subscription(
            status=SubscriptionStatus.PENDENTE,
            plan=plan,
            user_id=test_user.id,
        )
        subs.seed(sub)

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_payment_approved",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.activate_subscription(sub.id)
            mock_notify.assert_called_once_with(test_user, sub)

    @pytest.mark.asyncio
    async def test_cancel_subscription_sends_notification(self, service, repos, test_user):
        """Testa que cancel_subscription envia notificação de cancelamento."""
        subs, plans, users = repos
        plan = make_plan()
        plans.seed(plan)

        users.seed(test_user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=test_user.id,
        )
        subs.seed(sub)

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_cancellation",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.cancel_subscription(sub.id, test_user.id, immediately=True)
            mock_notify.assert_called_once_with(test_user, sub)

    @pytest.mark.asyncio
    async def test_reactivate_subscription_sends_notification(self, service, repos, test_user):
        """Testa que reactivate_subscription envia notificação de reativação."""
        subs, plans, users = repos
        plan = make_plan()
        plans.seed(plan)

        users.seed(test_user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=test_user.id,
            cancel_at_period_end=True,
        )
        subs.seed(sub)

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_reactivation",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.reactivate_subscription(sub.id, test_user.id)
            mock_notify.assert_called_once_with(test_user, sub)

    @pytest.mark.asyncio
    async def test_renew_subscription_sends_notification(self, service, repos, test_user):
        """Testa que renew_subscription envia notificação de renovação."""
        subs, plans, users = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)

        users.seed(test_user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=test_user.id,
        )
        subs.seed(sub)

        payment_id = uuid.uuid4()

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_renewal_success",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.renew_subscription(sub.id, test_user.id, payment_id)
            mock_notify.assert_called_once_with(test_user, sub)

    @pytest.mark.asyncio
    async def test_mark_payment_failed_sends_notification(self, service, repos, test_user):
        """Testa que mark_payment_failed envia notificação de falha."""
        subs, plans, users = repos
        plan = make_plan()
        plans.seed(plan)

        users.seed(test_user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=test_user.id,
        )
        subs.seed(sub)

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_payment_failed",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.mark_payment_failed(sub.id)
            mock_notify.assert_called_once_with(test_user, sub)

    @pytest.mark.asyncio
    async def test_change_plan_sends_notification(self, service, repos, test_user):
        """Testa que change_plan envia notificação de mudança de plano."""
        subs, plans, users = repos
        old_plan = make_plan(slug="standard", name="Standard", price_cents=2990)
        new_plan = make_plan(slug="pro", name="Pro", price_cents=4990)
        plans.seed(old_plan, new_plan)

        users.seed(test_user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=old_plan,
            user_id=test_user.id,
        )
        subs.seed(sub)

        # Patch do PaymentService.charge_prorated para não cobrar de verdade
        # e retornar um Payment APROVADO
        with patch(
            "app.services.billing.payment_service.PaymentService.charge_prorated",
            new_callable=AsyncMock,
        ) as mock_charge_prorated:
            # Criar um mock de Payment com status APROVADO
            mock_payment = MagicMock()
            mock_payment.status = PaymentStatus.APROVADO
            mock_payment.id = uuid.uuid4()
            mock_charge_prorated.return_value = mock_payment

            with patch(
                "app.services.billing.notification_service.SubscriptionNotificationService.notify_plan_change",
                new_callable=AsyncMock,
            ) as mock_notify:
                await service.change_plan(sub.id, test_user.id, new_plan.id)
                mock_notify.assert_called_once_with(test_user, sub, old_plan.name)

    @pytest.mark.asyncio
    async def test_dunning_recovered_sends_notification(self, service, repos, test_user):
        """Testa que recover_from_dunning envia notificação de recuperação."""
        subs, plans, users = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        plans.seed(plan)

        users.seed(test_user)

        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            user_id=test_user.id,
            dunning_attempts=2,
        )
        subs.seed(sub)

        payment_id = uuid.uuid4()

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_dunning_recovered",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.recover_from_dunning(sub.id, payment_id)
            mock_notify.assert_called_once_with(test_user, sub)

    @pytest.mark.asyncio
    async def test_dunning_retry_failed_sends_notification(self, service, repos, test_user):
        """Testa que record_dunning_retry_failure envia notificação de falha de retry."""
        subs, plans, users = repos
        plan = make_plan()
        plans.seed(plan)

        users.seed(test_user)

        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            user_id=test_user.id,
            dunning_attempts=0,
            dunning_next_retry_at=now,
        )
        subs.seed(sub)

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_dunning_retry_failed",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.record_dunning_retry_failure(sub.id)
            mock_notify.assert_called_once_with(test_user, sub)

    @pytest.mark.asyncio
    async def test_dunning_expired_sends_notification(self, service, repos, test_user):
        """Testa que expire_from_dunning envia notificação de expiração."""
        subs, plans, users = repos
        plan = make_plan()
        plans.seed(plan)

        users.seed(test_user)

        now = datetime.now(UTC)
        sub = make_subscription(
            status=SubscriptionStatus.INADIMPLENTE,
            plan=plan,
            user_id=test_user.id,
            dunning_grace_period_ends_at=now - timedelta(hours=1),
        )
        subs.seed(sub)

        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_dunning_expired",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.expire_from_dunning(sub.id)
            mock_notify.assert_called_once_with(test_user, sub)

    @pytest.mark.asyncio
    async def test_expire_subscription_does_not_send_notification(self, service, repos, test_user):
        """Testa que expire_subscription (ATIVA -> EXPIRADA) NÃO envia notificação.
        
        Este evento é uma transição de estado que não tem notificação associada
        no PROMPT 13 (apenas dunning_expired cobre expiração por inadimplência).
        """
        subs, plans, users = repos
        plan = make_plan()
        plans.seed(plan)

        users.seed(test_user)

        sub = make_subscription(
            status=SubscriptionStatus.ATIVA,
            plan=plan,
            user_id=test_user.id,
        )
        subs.seed(sub)

        # Nenhum patch de notificação deve ser chamado
        with patch(
            "app.services.billing.notification_service.SubscriptionNotificationService.notify_payment_failed",
            new_callable=AsyncMock,
        ) as mock_notify:
            await service.expire_subscription(sub.id)
            mock_notify.assert_not_called()