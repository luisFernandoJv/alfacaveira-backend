"""Abstração do provedor de pagamento.

Decisão de design (mesmo espírito do `EMAIL_DRIVER` em `email_service.py`):

Em vez de acoplar o projeto a um provedor específico (Stripe, Pagar.me,
Mercado Pago...) antes de haver uma escolha de negócio definida, os services
de billing dependem apenas do Protocol `PaymentGateway`. Hoje existe um único
driver, selecionável por variável de ambiente (`PAYMENT_GATEWAY_DRIVER`):

- `console` (padrão): não fala com nenhum provedor real. Aprova a cobrança
  imediatamente e apenas loga o evento formatado via `structlog` — deixa o
  fluxo de assinatura/pagamento 100% testável em desenvolvimento (e em
  qualquer ambiente novo) sem exigir nenhuma credencial externa.

Quando a equipe decidir o provedor definitivo, um novo driver implementa
`PaymentGateway` aqui (ex.: `StripeGateway`) e é registrado em
`_GATEWAY_FACTORIES` — nenhuma mudança é necessária em
`PaymentService`/`SubscriptionService` nem nos endpoints, pois eles conhecem
apenas o Protocol.

ADR-016 (docs/DECISIONS.md): o Protocol agora também define
`parse_webhook_event`, o ponto de verificação de assinatura + parsing do
payload bruto do provedor. Antes desta sessão, essa responsabilidade estava
hardcoded em `app/api/v1/billing/webhooks.py` como uma única checagem HMAC
genérica — o que não corresponde a como nenhum provedor real de fato assina
webhooks (Stripe, Mercado Pago e Pagar.me usam, cada um, um esquema próprio
de header/algoritmo). Mover isso para dentro de cada driver significa que
integrar um provedor real não vai exigir tocar no endpoint HTTP, só
implementar `charge` e `parse_webhook_event` no novo driver.
"""

import hmac
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import structlog
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import UnauthorizedError, ValidationDomainError
from app.models.enums import PaymentStatus

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChargeResult:
    """Resultado de uma tentativa de cobrança no provedor."""

    provider: str
    provider_payment_id: str
    status: PaymentStatus


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    """Evento de confirmação de pagamento já normalizado.

    Produzido por `PaymentGateway.parse_webhook_event` depois que o driver
    verificou a autenticidade do payload bruto (assinatura, segundo o esquema
    do provedor) e extraiu os campos relevantes. `PaymentService` e o
    endpoint de webhook só conhecem este formato — nunca o payload
    específico de nenhum provedor.
    """

    provider_payment_id: str
    status: PaymentStatus


class PaymentGateway(Protocol):
    """Contrato mínimo que todo driver de pagamento deve cumprir.

    Definido como Protocol (duck typing estrutural) para permitir um gateway
    fake em testes de `PaymentService`/`SubscriptionService`, sem depender de
    nenhum SDK real.
    """

    provider_name: str

    async def charge(
        self, *, amount_cents: int, currency: str, subscription_id: uuid.UUID
    ) -> ChargeResult: ...

    async def parse_webhook_event(
        self, *, raw_body: bytes, headers: Mapping[str, str]
    ) -> WebhookEvent:
        """Verifica a autenticidade do payload bruto do webhook e faz o
        parsing para `WebhookEvent`.

        Cada driver real implementa isto de acordo com o esquema específico
        do seu provedor (nome de header, algoritmo de assinatura, formato do
        corpo) — nenhum desses detalhes é decidido aqui, propositalmente,
        porque o provedor definitivo ainda não foi escolhido (ver ADR-004 e
        ADR-016).

        Deve levantar:
        - `UnauthorizedError` para assinatura ausente/inválida (o endpoint
          responde 401);
        - `ValidationDomainError` para payload malformado/incompreensível
          (o endpoint responde 422).
        """
        ...


class ConsoleGateway:
    """Driver default: aprova toda cobrança na hora, sem processar nada de
    verdade. Gera um `provider_payment_id` sintético (uuid4) só para exercer
    a idempotência de webhook (`PaymentRepository.get_by_provider_payment_id`)
    nos mesmos moldes de um provedor real.
    """

    provider_name = "console"

    async def charge(
        self, *, amount_cents: int, currency: str, subscription_id: uuid.UUID
    ) -> ChargeResult:
        provider_payment_id = str(uuid.uuid4())
        logger.info(
            "payment_gateway.charge (console driver — nenhuma cobrança real foi feita)",
            subscription_id=str(subscription_id),
            amount_cents=amount_cents,
            currency=currency,
            provider_payment_id=provider_payment_id,
        )
        return ChargeResult(
            provider=self.provider_name,
            provider_payment_id=provider_payment_id,
            status=PaymentStatus.APROVADO,
        )

    async def parse_webhook_event(
        self, *, raw_body: bytes, headers: Mapping[str, str]
    ) -> WebhookEvent:
        """Verificação e parsing do driver `console`.

        Não fala com nenhum provedor real, então não há assinatura de
        verdade para validar — o esquema abaixo (HMAC de tempo constante de
        um segredo estático contra o header `X-Webhook-Signature`) é só uma
        simulação para exercitar o fluxo de ponta a ponta em desenvolvimento
        e é o que o `CheckoutDialog` do frontend chama diretamente quando
        `PAYMENT_GATEWAY_DRIVER=console` (ver ADR-015). Comportamento
        idêntico ao que existia antes desta sessão em
        `app/api/v1/billing/webhooks.py::_verify_signature` — só realocado
        para trás do Protocol, sem mudança observável para quem já chama o
        endpoint hoje.

        NÃO é um template para um driver real copiar: nenhum provedor de
        pagamento de verdade assina webhooks comparando um segredo estático
        direto contra o corpo bruto. Um driver real deve seguir o esquema de
        assinatura documentado pelo próprio provedor (ex.: HMAC sobre
        `timestamp + payload`, com janela de tolerância contra replay).
        """
        # Import local (não no topo do módulo) para não fazer o services/
        # depender de schemas/ na inicialização do pacote — só este driver
        # (console) reaproveita o schema normalizado para parsing; um driver
        # real não precisaria disso, já que faria seu próprio parsing do
        # payload nativo do provedor.
        from app.schemas.billing.payment import PaymentWebhookEventRequest

        signature = headers.get("x-webhook-signature")
        if settings.PAYMENT_WEBHOOK_SECRET and (
            signature is None
            or not hmac.compare_digest(signature, settings.PAYMENT_WEBHOOK_SECRET)
        ):
            raise UnauthorizedError("Assinatura do webhook inválida.")

        try:
            payload = json.loads(raw_body)
            event = PaymentWebhookEventRequest.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ValidationDomainError(
                "Payload do webhook (driver console) malformado."
            ) from exc

        return WebhookEvent(
            provider_payment_id=event.provider_payment_id, status=event.status
        )


# Registro de drivers disponíveis, por nome de `PAYMENT_GATEWAY_DRIVER`.
# Cada entrada é um construtor sem argumentos — quando um provedor real for
# integrado (ex.: "stripe"), adicionar aqui: "stripe": StripeGateway.
_GATEWAY_FACTORIES: dict[str, type[PaymentGateway]] = {
    "console": ConsoleGateway,
}


def get_payment_gateway() -> PaymentGateway:
    """Resolve o driver configurado em `PAYMENT_GATEWAY_DRIVER`.

    Levanta `ValueError` explicitamente para um driver desconhecido, em vez
    de cair silenciosamente no driver `console` — subir em produção com um
    valor de configuração incorreto deve falhar de forma barulhenta, não
    processar pagamentos com o driver errado.
    """
    driver = settings.PAYMENT_GATEWAY_DRIVER
    try:
        gateway_cls = _GATEWAY_FACTORIES[driver]
    except KeyError:
        raise ValueError(
            f"PAYMENT_GATEWAY_DRIVER='{driver}' não é um driver de pagamento "
            f"conhecido. Drivers disponíveis: {sorted(_GATEWAY_FACTORIES)}."
        ) from None
    return gateway_cls()