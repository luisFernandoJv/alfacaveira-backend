"""Testes unitários de `ConsoleGateway.parse_webhook_event`
(`app/services/billing/gateway.py`, ADR-016).

Cobre a verificação de assinatura + parsing do payload bruto do webhook, que
antes desta sessão vivia como `_verify_signature` isolado em
`app/api/v1/billing/webhooks.py` e não tinha nenhum teste dedicado — a
factory (`get_payment_gateway`) e a validação de `Settings` já eram
cobertas por `test_billing_gateway_config.py` (PROMPT 02), mas a
verificação de assinatura em si não.

Não depende de banco de dados nem de Redis — só de `Settings` e do driver
`console`, mesmo espírito de `test_billing_gateway_config.py`.
"""

import json

import pytest

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError, ValidationDomainError
from app.models.enums import PaymentStatus
from app.services.billing import gateway as gateway_module
from app.services.billing.gateway import ConsoleGateway, WebhookEvent


@pytest.fixture
def gateway() -> ConsoleGateway:
    return ConsoleGateway()


def _valid_body(provider_payment_id: str = "pay_123", status: str = "aprovado") -> bytes:
    return json.dumps({"provider_payment_id": provider_payment_id, "status": status}).encode()


class TestParseWebhookEventWithoutSecretConfigured:
    """`PAYMENT_WEBHOOK_SECRET=""` é o default em desenvolvimento (driver
    console) — a checagem de assinatura é pulada de propósito."""

    async def test_accepts_payload_without_any_signature_header(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="")
        )

        event = await gateway.parse_webhook_event(raw_body=_valid_body(), headers={})

        assert event == WebhookEvent(
            provider_payment_id="pay_123", status=PaymentStatus.APROVADO
        )

    async def test_accepts_payload_even_with_a_bogus_signature_header(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem segredo configurado não há nada para comparar — um header
        presente e incorreto não deve, por si só, rejeitar o evento."""
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="")
        )

        event = await gateway.parse_webhook_event(
            raw_body=_valid_body(), headers={"x-webhook-signature": "qualquer-coisa"}
        )

        assert event.provider_payment_id == "pay_123"


class TestParseWebhookEventWithSecretConfigured:
    async def test_accepts_correct_signature(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="segredo-de-teste")
        )

        event = await gateway.parse_webhook_event(
            raw_body=_valid_body(), headers={"x-webhook-signature": "segredo-de-teste"}
        )

        assert event.status == PaymentStatus.APROVADO

    async def test_rejects_missing_signature_header(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="segredo-de-teste")
        )

        with pytest.raises(UnauthorizedError):
            await gateway.parse_webhook_event(raw_body=_valid_body(), headers={})

    async def test_rejects_wrong_signature(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="segredo-de-teste")
        )

        with pytest.raises(UnauthorizedError):
            await gateway.parse_webhook_event(
                raw_body=_valid_body(), headers={"x-webhook-signature": "segredo-errado"}
            )

    async def test_signature_check_happens_before_payload_parsing(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Um payload malformado com assinatura inválida deve falhar por
        assinatura (401), não por payload (422) — não vazar informação sobre
        o corpo antes de autenticar quem está chamando."""
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="segredo-de-teste")
        )

        with pytest.raises(UnauthorizedError):
            await gateway.parse_webhook_event(
                raw_body=b"isto nao e json",
                headers={"x-webhook-signature": "segredo-errado"},
            )


class TestParseWebhookEventMalformedPayload:
    async def test_rejects_invalid_json(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="")
        )

        with pytest.raises(ValidationDomainError):
            await gateway.parse_webhook_event(raw_body=b"isto nao e json", headers={})

    async def test_rejects_missing_provider_payment_id(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="")
        )
        body = json.dumps({"status": "aprovado"}).encode()

        with pytest.raises(ValidationDomainError):
            await gateway.parse_webhook_event(raw_body=body, headers={})

    async def test_rejects_unknown_status_value(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="")
        )
        body = _valid_body(status="nao-existe")

        with pytest.raises(ValidationDomainError):
            await gateway.parse_webhook_event(raw_body=body, headers={})

    async def test_rejects_empty_body(
        self, gateway: ConsoleGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gateway_module, "settings", Settings(PAYMENT_WEBHOOK_SECRET="")
        )

        with pytest.raises(ValidationDomainError):
            await gateway.parse_webhook_event(raw_body=b"", headers={})