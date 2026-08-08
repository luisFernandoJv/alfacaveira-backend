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
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

import structlog

from app.core.config import settings
from app.models.enums import PaymentStatus

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChargeResult:
    """Resultado de uma tentativa de cobrança no provedor."""

    provider: str
    provider_payment_id: str
    status: PaymentStatus


class PaymentGateway(Protocol):
    """Contrato mínimo que todo driver de pagamento deve cumprir.

    Definido como Protocol (duck typing estrutural) para permitir um gateway
    fake em testes de `PaymentService`/`SubscriptionService`, sem depender de
    nenhum SDK real.
    """

    async def charge(
        self, *, amount_cents: int, currency: str, subscription_id: uuid.UUID
    ) -> ChargeResult: ...


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