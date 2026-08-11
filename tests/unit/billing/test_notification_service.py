# tests/unit/billing/test_notification_service.py
# Substitua o arquivo inteiro por este:

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.models.identity.user import User
from app.services.billing.notification_service import SubscriptionNotificationService
from tests.unit.billing.factories import make_plan, make_subscription


class TestSubscriptionNotificationService:
    """Testes do SubscriptionNotificationService (PROMPT 13)."""

    @pytest.fixture
    def user(self):
        return User(
            id=uuid.uuid4(),
            email="teste@teste.com",
            full_name="Usuário Teste",
            is_active=True,
        )

    @pytest.fixture
    def subscription(self):
        plan = make_plan(slug="pro", name="Pro", price_cents=4990)
        return make_subscription(plan=plan)

    @pytest.fixture
    def notification_service(self):
        return SubscriptionNotificationService()

    # ==================================================================== #
    # Testes: Pagamento                                                    #
    # ==================================================================== #

    @pytest.mark.asyncio
    async def test_notify_payment_approved(self, user, subscription, notification_service):
        """Testa notificação de pagamento aprovado."""
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_payment_approved(user, subscription)
            mock_send.assert_called_once_with(
                to_email=user.email,
                to_name=user.full_name,
                subject="Pagamento aprovado — Foco Policial",
                template_name="payment_approved",
                context={
                    "first_name": "Usuário",
                    "plan_name": "Pro",
                    "amount": 49.9,
                },
            )

    @pytest.mark.asyncio
    async def test_notify_payment_approved_disabled(self, user, subscription, monkeypatch):
        """Testa que notificação não é enviada se desabilitada."""
        monkeypatch.setattr(settings, "NOTIFY_PAYMENT_APPROVED", False)
        service = SubscriptionNotificationService()
        with patch.object(service._email_service, "send_email", new_callable=AsyncMock) as mock_send:
            await service.notify_payment_approved(user, subscription)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_payment_failed(self, user, subscription, notification_service):
        """Testa notificação de falha de pagamento."""
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_payment_failed(user, subscription)
            mock_send.assert_called_once_with(
                to_email=user.email,
                to_name=user.full_name,
                subject="Falha no pagamento — Foco Policial",
                template_name="payment_failed",
                context={
                    "first_name": "Usuário",
                    "plan_name": "Pro",
                    "amount": 49.9,
                },
            )

    # ==================================================================== #
    # Testes: Renovação                                                    #
    # ==================================================================== #

    @pytest.mark.asyncio
    async def test_notify_renewal_success(self, user, subscription, notification_service):
        """Testa notificação de renovação bem-sucedida."""
        subscription.current_period_end = datetime.now() + timedelta(days=30)
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_renewal_success(user, subscription)
            mock_send.assert_called_once()
            context = mock_send.call_args[1]["context"]
            assert "next_renewal" in context
            assert context["first_name"] == "Usuário"

    @pytest.mark.asyncio
    async def test_notify_renewal_reminder(self, user, subscription, notification_service):
        """Testa notificação de lembrete de renovação."""
        subscription.current_period_end = datetime.now() + timedelta(
            days=settings.RENEWAL_REMINDER_DAYS_BEFORE
        )
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_renewal_reminder(user, subscription)
            mock_send.assert_called_once()
            context = mock_send.call_args[1]["context"]
            assert context["days_left"] == settings.RENEWAL_REMINDER_DAYS_BEFORE
            assert context["first_name"] == "Usuário"

    @pytest.mark.asyncio
    async def test_notify_renewal_reminder_too_early(self, user, subscription, notification_service):
        """Testa que lembrete não é enviado se ainda não chegou o prazo."""
        subscription.current_period_end = datetime.now() + timedelta(
            days=settings.RENEWAL_REMINDER_DAYS_BEFORE + 5
        )
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_renewal_reminder(user, subscription)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_renewal_reminder_disabled(self, user, subscription, monkeypatch):
        """Testa que lembrete não é enviado se desabilitado."""
        monkeypatch.setattr(settings, "NOTIFY_RENEWAL_REMINDER", False)
        subscription.current_period_end = datetime.now() + timedelta(
            days=settings.RENEWAL_REMINDER_DAYS_BEFORE
        )
        service = SubscriptionNotificationService()
        with patch.object(service._email_service, "send_email", new_callable=AsyncMock) as mock_send:
            await service.notify_renewal_reminder(user, subscription)
            mock_send.assert_not_called()

    # ==================================================================== #
    # Testes: Gerenciamento                                                #
    # ==================================================================== #

    @pytest.mark.asyncio
    async def test_notify_cancellation(self, user, subscription, notification_service):
        """Testa notificação de cancelamento."""
        subscription.current_period_end = datetime.now() + timedelta(days=15)
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_cancellation(user, subscription)
            mock_send.assert_called_once()
            context = mock_send.call_args[1]["context"]
            assert "expiration_date" in context
            assert context["first_name"] == "Usuário"

    @pytest.mark.asyncio
    async def test_notify_reactivation(self, user, subscription, notification_service):
        """Testa notificação de reativação."""
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_reactivation(user, subscription)
            mock_send.assert_called_once_with(
                to_email=user.email,
                to_name=user.full_name,
                subject="Plano reativado — Foco Policial",
                template_name="reactivation",
                context={
                    "first_name": "Usuário",
                    "plan_name": "Pro",
                    "amount": 49.9,
                },
            )

    @pytest.mark.asyncio
    async def test_notify_plan_change(self, user, subscription, notification_service):
        """Testa notificação de mudança de plano."""
        old_plan_name = "Standard"
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_plan_change(user, subscription, old_plan_name)
            mock_send.assert_called_once()
            context = mock_send.call_args[1]["context"]
            assert context["old_plan"] == old_plan_name
            assert context["new_plan"] == subscription.plan.name
            assert context["first_name"] == "Usuário"

    # ==================================================================== #
    # Testes: Dunning                                                      #
    # ==================================================================== #

    @pytest.mark.asyncio
    async def test_notify_dunning_recovered(self, user, subscription, notification_service):
        """Testa notificação de recuperação de dunning."""
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_dunning_recovered(user, subscription)
            mock_send.assert_called_once_with(
                to_email=user.email,
                to_name=user.full_name,
                subject="Pagamento regularizado — Foco Policial",
                template_name="dunning_recovered",
                context={
                    "first_name": "Usuário",
                    "plan_name": "Pro",
                    "amount": 49.9,
                },
            )

    @pytest.mark.asyncio
    async def test_notify_dunning_retry_failed(self, user, subscription, notification_service):
        """Testa notificação de falha de retry de dunning."""
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_dunning_retry_failed(user, subscription)
            mock_send.assert_called_once_with(
                to_email=user.email,
                to_name=user.full_name,
                subject="Pagamento falhou novamente — Foco Policial",
                template_name="dunning_retry_failed",
                context={
                    "first_name": "Usuário",
                    "plan_name": "Pro",
                    "amount": 49.9,
                },
            )

    @pytest.mark.asyncio
    async def test_notify_dunning_expired(self, user, subscription, notification_service):
        """Testa notificação de expiração por dunning."""
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_dunning_expired(user, subscription)
            mock_send.assert_called_once_with(
                to_email=user.email,
                to_name=user.full_name,
                subject="Plano expirado — Foco Policial",
                template_name="dunning_expired",
                context={
                    "first_name": "Usuário",
                    "plan_name": "Pro",
                    "amount": 49.9,
                },
            )

    # ==================================================================== #
    # Testes: Comportamento Geral                                          #
    # ==================================================================== #

    @pytest.mark.asyncio
    async def test_email_failure_does_not_propagate(self, user, subscription, notification_service):
        """Testa que falha de e-mail nunca propaga exceção."""
        with patch.object(
            notification_service._email_service,
            "send_email",
            side_effect=Exception("SMTP failure"),
        ) as mock_send:
            # Não deve levantar exceção
            await notification_service.notify_payment_approved(user, subscription)
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_notification_uses_first_name(self, user, subscription, notification_service):
        """Testa que o primeiro nome é extraído corretamente."""
        user.full_name = "Maria Clara Santos"
        with patch.object(
            notification_service._email_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await notification_service.notify_payment_approved(user, subscription)
            context = mock_send.call_args[1]["context"]
            assert context["first_name"] == "Maria"