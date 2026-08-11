# tests/unit/test_email_service.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.config import settings
from app.services.identity.email_service import EmailService


class TestEmailService:
    """Testes do EmailService, incluindo o novo método send_email."""

    @pytest.fixture
    def email_service(self):
        return EmailService()

    @pytest.mark.asyncio
    async def test_send_password_reset_email_console_driver(self, email_service):
        """Testa envio de e-mail de recuperação de senha com driver console."""
        with patch.object(email_service, "_send_via_console") as mock_console:
            await email_service.send_password_reset_email(
                to_email="teste@teste.com",
                to_name="João Silva",
                reset_url="https://focopolicial.com/reset?token=123",
            )
            mock_console.assert_called_once()
            args = mock_console.call_args[1]
            assert args["to_email"] == "teste@teste.com"
            assert "Redefinição de senha" in args["subject"]
            assert "João" in args["text_body"]

    @pytest.mark.asyncio
    async def test_send_password_reset_email_smtp_driver(self, email_service, monkeypatch):
        """Testa envio de e-mail de recuperação de senha com driver SMTP."""
        monkeypatch.setattr(settings, "EMAIL_DRIVER", "smtp")
        with patch.object(email_service, "_send_via_smtp", new_callable=AsyncMock) as mock_smtp:
            await email_service.send_password_reset_email(
                to_email="teste@teste.com",
                to_name="João Silva",
                reset_url="https://focopolicial.com/reset?token=123",
            )
            mock_smtp.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_console_driver(self, email_service):
        """Testa envio de e-mail transacional com driver console."""
        with patch.object(email_service, "_send_via_console") as mock_console:
            await email_service.send_email(
                to_email="teste@teste.com",
                to_name="João Silva",
                subject="Pagamento aprovado",
                template_name="payment_approved",
                context={
                    "plan_name": "Pro",
                    "amount": 49.90,
                },
            )
            mock_console.assert_called_once()
            args = mock_console.call_args[1]
            assert args["to_email"] == "teste@teste.com"
            assert args["subject"] == "Pagamento aprovado"
            assert "João" in args["text_body"]
            assert "Pro" in args["text_body"]

    @pytest.mark.asyncio
    async def test_send_email_smtp_driver(self, email_service, monkeypatch):
        """Testa envio de e-mail transacional com driver SMTP."""
        monkeypatch.setattr(settings, "EMAIL_DRIVER", "smtp")
        with patch.object(email_service, "_send_via_smtp", new_callable=AsyncMock) as mock_smtp:
            await email_service.send_email(
                to_email="teste@teste.com",
                to_name="João Silva",
                subject="Pagamento aprovado",
                template_name="payment_approved",
                context={
                    "plan_name": "Pro",
                    "amount": 49.90,
                },
            )
            mock_smtp.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_template_not_found(self, email_service):
        """Testa comportamento quando template não existe."""
        with patch.object(email_service, "_send_via_console") as mock_console:
            await email_service.send_email(
                to_email="teste@teste.com",
                to_name="João Silva",
                subject="Teste",
                template_name="template_inexistente",
                context={},
            )
            mock_console.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_email_missing_context_key(self, email_service):
        """Testa comportamento quando falta chave no contexto."""
        with patch.object(email_service, "_send_via_console") as mock_console:
            await email_service.send_email(
                to_email="teste@teste.com",
                to_name="João Silva",
                subject="Teste",
                template_name="payment_approved",
                context={},  # faltando plan_name e amount
            )
            mock_console.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_via_smtp_success(self, email_service, monkeypatch):
        """Testa envio via SMTP com sucesso."""
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test.com")
        monkeypatch.setattr(settings, "SMTP_PORT", 587)
        monkeypatch.setattr(settings, "SMTP_USER", "user")
        monkeypatch.setattr(settings, "SMTP_PASSWORD", "pass")
        monkeypatch.setattr(settings, "SMTP_USE_TLS", True)

        with patch("smtplib.SMTP") as mock_smtp:
            mock_client = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_client
            await email_service._send_via_smtp(
                to_email="teste@teste.com",
                subject="Teste",
                text_body="Texto",
                html_body="<html>HTML</html>",
            )
            mock_client.starttls.assert_called_once()
            mock_client.login.assert_called_once_with("user", "pass")
            mock_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_via_smtp_failure_logs_error(self, email_service, monkeypatch):
        """Testa que falha de SMTP é logada mas não propaga."""
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test.com")
        monkeypatch.setattr(settings, "SMTP_PORT", 587)

        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.side_effect = ConnectionError("Falha de conexão")
            # Não deve levantar exceção
            await email_service._send_via_smtp(
                to_email="teste@teste.com",
                subject="Teste",
                text_body="Texto",
                html_body="<html>HTML</html>",
            )