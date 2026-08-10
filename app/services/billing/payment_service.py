"""Regras de negócio de `Payment`: iniciar uma cobrança via `PaymentGateway`
e processar a confirmação assíncrona (webhook) de forma idempotente.

`PaymentRepository.get_by_provider_payment_id` é a base da idempotência
*de negócio*: se o evento do provedor já foi registrado com o mesmo status,
`process_webhook_event` não reprocessa — importante porque retry de evento é
padrão em gateways de pagamento reais. O parsing/validação de assinatura do
payload do webhook fica na Etapa 4 (`app/api/v1/billing/webhooks.py`); este
service só recebe `provider_payment_id` + `status` já extraídos.

PROMPT 05: além do efeito colateral já existente sobre falha de pagamento
(`mark_payment_failed`), um evento APROVADO agora também pode *ativar* uma
assinatura PENDENTE (`SubscriptionService.activate_subscription`) — é assim
que o fluxo alvo "Webhook validado -> Payment APPROVED -> Subscription
ACTIVE" (PROJECT_STATE.md §6) se conecta ao restante do código. Ver ADR-014.

Roadmap item 7 / ADR-017 (esta sessão): a checagem `payment.status ==
status` no início de `process_webhook_event` cobre reentrega *sequencial*
do mesmo evento, mas não duas entregas *concorrentes* chegando quase juntas
— ambas podem ler o status antigo antes de qualquer uma escrever, e as
duas prosseguiriam para aplicar o efeito colateral na assinatura (mesma
forma do achado já documentado em `mark_payment_failed`, ver
`SubscriptionService`). A escrita do novo status agora passa por
`PaymentRepository.compare_and_swap_status`; só quem vence o CAS aciona o
efeito colateral (`mark_payment_failed`/`activate_subscription`) — quem
perde trata como reentrega idempotente e não toca a assinatura de novo.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database.uow import UnitOfWork
from app.models.billing.payment import Payment
from app.models.enums import PaymentStatus, SubscriptionStatus
from app.repositories.billing.payment_repository import PaymentRepository
from app.repositories.billing.subscription_repository import SubscriptionRepository
from app.services.billing.gateway import PaymentGateway, get_payment_gateway
from app.services.billing.subscription_service import SubscriptionService


class PaymentService:
    def __init__(self, session: AsyncSession, gateway: PaymentGateway | None = None) -> None:
        self._session = session
        self._payments = PaymentRepository(session)
        self._subscriptions = SubscriptionRepository(session)
        self._gateway = gateway or get_payment_gateway()
        # Composição, não herança: reaproveita as transições de status já
        # centralizadas em `SubscriptionService` (ex.: `mark_payment_failed`,
        # `activate_subscription`) em vez de duplicar a lógica de
        # `SubscriptionHistory` aqui.
        self._subscription_service = SubscriptionService(session)

    async def list_by_subscription(self, subscription_id: uuid.UUID) -> list[Payment]:
        return await self._payments.list_by_subscription(subscription_id)

    async def charge_subscription(self, subscription_id: uuid.UUID) -> Payment:
        """Inicia a cobrança do período corrente/próximo de uma assinatura,
        via o `PaymentGateway` configurado (`PAYMENT_GATEWAY_DRIVER`).

        Só registra o `Payment` — mesmo que o gateway aprove de forma
        síncrona (caso do driver `console`), a ativação da assinatura
        continua acontecendo exclusivamente via `process_webhook_event`
        (ver ADR-014). Isso mantém uma única porta de entrada para
        transições de estado de `Subscription` a partir de eventos de
        pagamento, em vez de duplicar a lógica aqui e no webhook.
        """
        subscription = await self._subscriptions.get_by_id_with_plan(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")

        result = await self._gateway.charge(
            amount_cents=subscription.plan.price_cents,
            currency="BRL",
            subscription_id=subscription.id,
        )

        payment = Payment(
            subscription_id=subscription.id,
            amount_cents=subscription.plan.price_cents,
            currency="BRL",
            status=result.status,
            provider=result.provider,
            provider_payment_id=result.provider_payment_id,
            paid_at=_utcnow() if result.status == PaymentStatus.APROVADO else None,
        )

        async with UnitOfWork(self._session):
            await self._payments.add(payment)

        return payment

    async def process_webhook_event(self, *, provider_payment_id: str, status: PaymentStatus) -> Payment:
        """Aplica a confirmação de um evento de webhook a um `Payment` já
        registrado por `charge_subscription`.

        Idempotente contra reentrega sequencial (a checagem `payment.status
        == status` abaixo) e agora também contra reentrega/concorrência
        real (roadmap item 7, ADR-017): a escrita do novo status usa
        `PaymentRepository.compare_and_swap_status`, que só aplica se o
        status em banco ainda for o que foi lido aqui. Duas chamadas
        concorrentes para o mesmo `Payment` (mesmo evento reentregue, ou
        dois eventos distintos chegando quase juntos) só deixam uma vencer
        o CAS — a outra não aciona `mark_payment_failed`/
        `activate_subscription` de novo, evitando duplicar
        `SubscriptionHistory` ou tentar ativar uma assinatura já ativada.
        """
        payment = await self._payments.get_by_provider_payment_id(provider_payment_id)
        if payment is None:
            raise NotFoundError(
                f"Pagamento com provider_payment_id '{provider_payment_id}' não encontrado."
            )
        if payment.status == status:
            return payment

        previous_status = payment.status
        paid_at = _utcnow() if status == PaymentStatus.APROVADO else None

        async with UnitOfWork(self._session):
            applied = await self._payments.compare_and_swap_status(
                payment.id,
                expected_status=previous_status,
                new_status=status,
                paid_at=paid_at,
            )
            if applied:
                payment.status = status
                if paid_at is not None:
                    payment.paid_at = paid_at
                await self._session.flush()

        if not applied:
            # Perdeu a corrida: outra entrega concorrente já aplicou uma
            # transição a este pagamento entre a leitura acima e o CAS.
            # Idempotente — não aciona o efeito colateral de novo.
            current = await self._payments.get_by_provider_payment_id(provider_payment_id)
            return current if current is not None else payment

        if status in (PaymentStatus.RECUSADO, PaymentStatus.ESTORNADO):
            await self._subscription_service.mark_payment_failed(payment.subscription_id)
        elif status == PaymentStatus.APROVADO:
            # O ramo depende do status atual da assinatura: um APROVADO
            # pode ser tanto o primeiro pagamento (ativação, PROMPT 05)
            # quanto a confirmação de uma cobrança de renovação (PROMPT 10
            # — roadmap item 10, implementado nesta sessão) de uma
            # assinatura que já estava ATIVA. Cada um vai para o service
            # certo — chamar `activate_subscription` numa assinatura já
            # ATIVA (ou `renew_subscription_system` numa ainda PENDENTE)
            # levantaria `ConflictError`, daí a checagem aqui antes de
            # chamar, em vez de deixar o service rejeitar.
            subscription = await self._subscriptions.get_by_id(payment.subscription_id)
            if subscription is not None:
                if subscription.status == SubscriptionStatus.PENDENTE:
                    await self._subscription_service.activate_subscription(payment.subscription_id)
                elif subscription.status == SubscriptionStatus.ATIVA:
                    await self._subscription_service.renew_subscription_system(
                        payment.subscription_id, payment_id=payment.id
                    )
                elif subscription.status == SubscriptionStatus.INADIMPLENTE:
                    # PROMPT 11 (dunning): um evento APROVADO para uma
                    # assinatura já INADIMPLENTE é uma recobrança bem-sucedida
                    # (caminho de um provedor assíncrono real — o driver
                    # console síncrono de hoje é aplicado diretamente pelo
                    # job de dunning, sem passar por aqui, mesmo raciocínio
                    # de ATIVA/renew_subscription_system já documentado
                    # acima e no docstring de
                    # app/workers/subscription_dunning.py).
                    await self._subscription_service.recover_from_dunning(
                        payment.subscription_id, payment_id=payment.id
                    )

        return payment


def _utcnow() -> datetime:
    return datetime.now(UTC)