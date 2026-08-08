"""Testes unitários da factory `get_payment_gateway` e da validação de
`PAYMENT_WEBHOOK_SECRET`/`PAYMENT_GATEWAY_DRIVER` em `Settings` (PROMPT 02).

Não dependem de banco de dados nem de Redis — testam apenas configuração e a
factory de driver, então não usam os fixtures de `tests/conftest.py`.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.billing import gateway as gateway_module
from app.services.billing.gateway import ConsoleGateway, get_payment_gateway


class TestGetPaymentGatewayFactory:
    def test_default_driver_returns_console_gateway(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gateway_module, "settings", Settings(PAYMENT_GATEWAY_DRIVER="console"))

        result = get_payment_gateway()

        assert isinstance(result, ConsoleGateway)

    def test_unknown_driver_raises_explicit_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_GATEWAY_DRIVER="stripe")
        )

        with pytest.raises(ValueError, match="stripe.*não é um driver"):
            get_payment_gateway()

    def test_empty_driver_raises_explicit_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gateway_module, "settings", Settings(PAYMENT_GATEWAY_DRIVER=""))

        with pytest.raises(ValueError):
            get_payment_gateway()


class TestSettingsProductionWebhookSecretValidation:
    def test_production_with_console_driver_allows_empty_secret(self) -> None:
        settings = Settings(
            APP_ENV="production",
            PAYMENT_GATEWAY_DRIVER="console",
            PAYMENT_WEBHOOK_SECRET="",
        )

        assert settings.PAYMENT_WEBHOOK_SECRET == ""

    def test_production_with_real_driver_and_empty_secret_fails(self) -> None:
        with pytest.raises(ValidationError, match="PAYMENT_WEBHOOK_SECRET"):
            Settings(
                APP_ENV="production",
                PAYMENT_GATEWAY_DRIVER="stripe",
                PAYMENT_WEBHOOK_SECRET="",
            )

    def test_production_with_real_driver_and_secret_configured_succeeds(self) -> None:
        settings = Settings(
            APP_ENV="production",
            PAYMENT_GATEWAY_DRIVER="stripe",
            PAYMENT_WEBHOOK_SECRET="a-real-secret",
        )

        assert settings.PAYMENT_WEBHOOK_SECRET == "a-real-secret"

    def test_development_with_real_driver_and_empty_secret_is_allowed(self) -> None:
        """A validação só é obrigatória em produção — em dev, um driver não
        implementado ainda falharia de qualquer forma na factory
        (`get_payment_gateway`), então não duplicamos a checagem aqui."""
        settings = Settings(
            APP_ENV="development",
            PAYMENT_GATEWAY_DRIVER="stripe",
            PAYMENT_WEBHOOK_SECRET="",
        )

        assert settings.PAYMENT_WEBHOOK_SECRET == ""

    def test_default_settings_are_valid(self) -> None:
        """Defaults (console, sem segredo) nunca devem falhar a validação,
        em nenhum APP_ENV — garante que dev/CI continuam subindo sem .env."""
        for env in ("development", "staging", "production"):
            Settings(APP_ENV=env)