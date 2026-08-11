"""Testes unitários de `PaymentService`.

Usa um `FakePaymentGateway` (dublê controlável, sem falar com nenhum
provedor real — ver ADR-004/ADR-006) injetado diretamente no construtor de
`PaymentService`, e `Fake*Repository` no lugar dos repositórios reais (ver
`tests/unit/billing/fakes.py`).

Cobre: início de cobrança (`charge_subscription`), idempotência do
processamento de webhook (`process_webhook_event` — ADR-005), o efeito
colateral de pagamento recusado/estornado sobre a assinatura (delega para
`SubscriptionService.mark_payment_failed`, ramificado por status de origem
desde o PROMPT 05), o efeito colateral de um pagamento aprovado sobre uma
assinatura PENDENTE (delega para `SubscriptionService.activate_subscription`
— PROMPT 05, ver ADR-014), e sobre uma assinatura já ATIVA (delega para
`SubscriptionService.renew_subscription_system` — PROMPT 10, roadmap item
10, recorrência).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import NotFoundError
from app.models.enums import PaymentStatus, SubscriptionHistoryReason, SubscriptionStatus
from app.services.billing import payment_service as payment_service_module
from app.services.billing import subscription_service as subscription_service_module
from app.services.billing.gateway import ChargeResult
from app.services.billing.payment_service import PaymentService
from tests.unit.billing.factories import make_payment, make_plan, make_subscription
from tests.unit.billing.fakes import (
    FakeAsyncSession,
    FakePaymentRepository,
    FakePlanRepository,
    FakeSubscriptionHistoryRepository,
    FakeSubscriptionRepository,
    FakeUserRepository,  # <-- ADICIONADO
)


class FakePaymentGateway:
    """Dublê controlável de `PaymentGateway` — resultado configurado pelo
    teste, sem falar com nenhum provedor real (ADR-004)."""

    provider_name = "fake"

    def __init__(self, status: PaymentStatus = PaymentStatus.APROVADO) -> None:
        self.status = status
        self.calls: list[dict] = []

    async def charge(
        self, *, amount_cents: int, currency: str, subscription_id: uuid.UUID
    ) -> ChargeResult:
        self.calls.append(
            {"amount_cents": amount_cents, "currency": currency, "subscription_id": subscription_id}
        )
        return ChargeResult(
            provider="fake", provider_payment_id=str(uuid.uuid4()), status=self.status
        )

    async def parse_webhook_event(self, *, raw_body: bytes, headers):
        """Não exercido por nenhum teste deste arquivo (só
        `PaymentService.process_webhook_event`, que já recebe o evento
        normalizado) — presente apenas para satisfazer o Protocol
        `PaymentGateway` (ADR-016) sob `mypy --strict`."""
        raise NotImplementedError


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch):
    payments = FakePaymentRepository()
    subs = FakeSubscriptionRepository()
    plans = FakePlanRepository()
    users = FakeUserRepository()  # <-- ADICIONADO

    monkeypatch.setattr(payment_service_module, "PaymentRepository", lambda session: payments)
    monkeypatch.setattr(payment_service_module, "SubscriptionRepository", lambda session: subs)

    # PaymentService compõe SubscriptionService internamente (mesma sessão) —
    # precisa dos mesmos dublês para que `mark_payment_failed` enxergue a
    # mesma assinatura semeada no teste.
    monkeypatch.setattr(subscription_service_module, "SubscriptionRepository", lambda session: subs)
    monkeypatch.setattr(subscription_service_module, "PlanRepository", lambda session: plans)
    # PROMPT 13: SubscriptionService agora tem hooks de notificação que usam UserRepository
    monkeypatch.setattr(
        subscription_service_module,
        "UserRepository",
        lambda session: users,
    )
    # PROMPT 10: um APROVADO sobre assinatura já ATIVA agora também aciona
    # `renew_subscription_system`, que consulta `SubscriptionHistoryRepository`
    # (idempotência por `payment_id`) — precisa do mesmo fake que
    # `test_subscription_service.py` já usa, ou o service tentaria falar
    # com um banco real inexistente.
    monkeypatch.setattr(
        subscription_service_module,
        "SubscriptionHistoryRepository",
        FakeSubscriptionHistoryRepository,
    )
    return payments, subs, plans


def make_service(
    repos, status: PaymentStatus = PaymentStatus.APROVADO
) -> tuple[PaymentService, FakePaymentGateway]:
    gateway = FakePaymentGateway(status=status)
    service = PaymentService(FakeAsyncSession(), gateway=gateway)
    return service, gateway


class TestChargeSubscription:
    async def test_creates_approved_payment_via_gateway(self, repos):
        payments, subs, plans = repos
        plan = make_plan(price_cents=4990)
        sub = make_subscription(plan=plan, status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        service, gateway = make_service(repos, status=PaymentStatus.APROVADO)

        payment = await service.charge_subscription(sub.id)

        assert payment.status == PaymentStatus.APROVADO
        assert payment.amount_cents == 4990
        assert payment.paid_at is not None
        assert gateway.calls[0]["subscription_id"] == sub.id

    async def test_pending_gateway_result_does_not_set_paid_at(self, repos):
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        service, gateway = make_service(repos, status=PaymentStatus.PENDENTE)

        payment = await service.charge_subscription(sub.id)

        assert payment.status == PaymentStatus.PENDENTE
        assert payment.paid_at is None

    async def test_rejects_unknown_subscription(self, repos):
        service, gateway = make_service(repos)

        with pytest.raises(NotFoundError):
            await service.charge_subscription(uuid.uuid4())


class TestProcessWebhookEvent:
    async def test_approves_pending_payment(self, repos):
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.PENDENTE)
        payments.seed(payment)
        service, _ = make_service(repos)

        result = await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.APROVADO
        )

        assert result.status == PaymentStatus.APROVADO
        assert result.paid_at is not None

    async def test_is_idempotent_for_repeated_event(self, repos):
        """Reenvio do mesmo evento (mesmo status) não deve reprocessar —
        base da idempotência de webhook, ADR-005."""
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.APROVADO)
        payments.seed(payment)
        service, _ = make_service(repos)

        result = await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.APROVADO
        )

        assert result is payment
        assert len(service._session.added) == 0

    async def test_recusado_marks_subscription_as_inadimplente(self, repos):
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.PENDENTE)
        payments.seed(payment)
        service, _ = make_service(repos)

        result = await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.RECUSADO
        )

        assert result.status == PaymentStatus.RECUSADO
        assert subs.store[sub.id].status == SubscriptionStatus.INADIMPLENTE

    async def test_recusado_cancels_pending_subscription(self, repos):
        """Novo no PROMPT 05 (ADR-014, decisão 2): se a falha é do pagamento
        de ativação (assinatura ainda PENDENTE), `mark_payment_failed` manda
        para CANCELADA, não INADIMPLENTE — este teste cobre o caminho de
        `process_webhook_event` até esse ramo, não só `mark_payment_failed`
        isolado (já coberto em `test_subscription_service.py`)."""
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.PENDENTE)
        subs.seed(sub)
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.PENDENTE)
        payments.seed(payment)
        service, _ = make_service(repos)

        result = await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.RECUSADO
        )

        assert result.status == PaymentStatus.RECUSADO
        assert subs.store[sub.id].status == SubscriptionStatus.CANCELADA

    async def test_aprovado_activates_pending_subscription(self, repos):
        """Novo no PROMPT 05 (ADR-014): o elo que fecha o fluxo alvo
        'Webhook validado -> Payment APROVADO -> Subscription ATIVA'
        (PROJECT_STATE.md §6) — `process_webhook_event` deve chamar
        `SubscriptionService.activate_subscription` quando o pagamento
        aprovado pertence a uma assinatura ainda PENDENTE."""
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.PENDENTE)
        subs.seed(sub)
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.PENDENTE)
        payments.seed(payment)
        service, _ = make_service(repos)

        result = await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.APROVADO
        )

        assert result.status == PaymentStatus.APROVADO
        assert subs.store[sub.id].status == SubscriptionStatus.ATIVA

    async def test_aprovado_renews_already_active_subscription(self, repos):
        """PROMPT 10 (roadmap item 10, recorrência — implementado nesta
        sessão): uma APROVADO para uma assinatura já ATIVA é a confirmação
        de uma cobrança de renovação (job automático ou `charge_subscription`
        manual), não uma segunda ativação — `process_webhook_event` deve
        chamar `SubscriptionService.renew_subscription_system` (que
        avançaria `activate_subscription` para `ConflictError`, por não ser
        PENDENTE)."""
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        old_period_end = sub.current_period_end
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.PENDENTE)
        payments.seed(payment)
        service, _ = make_service(repos)

        result = await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.APROVADO
        )

        assert result.status == PaymentStatus.APROVADO
        assert subs.store[sub.id].status == SubscriptionStatus.ATIVA
        assert subs.store[sub.id].current_period_end > old_period_end
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert history_entries[0].reason == SubscriptionHistoryReason.RENOVADA
        assert history_entries[0].payment_id == payment.id

    async def test_aprovado_renewal_is_idempotent_for_repeated_webhook_delivery(self, repos):
        """Reentrega do mesmo evento de renovação (mesmo `payment_id`) não
        avança o período uma segunda vez — mesma idempotência de
        `TestRenewSubscriptionSystem.test_repeated_payment_id_is_idempotent_no_op`
        (test_subscription_service.py), exercida agora pelo caminho
        completo do webhook. É o que garante, na prática, que o job de
        renovação automática (PROMPT 10) rodar duas vezes não duplica
        cobrança."""
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        old_period_end = sub.current_period_end
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.PENDENTE)
        payments.seed(payment)
        service, _ = make_service(repos)

        await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.APROVADO
        )
        first_period_end = subs.store[sub.id].current_period_end

        # Reentrega: mesmo `provider_payment_id`, mesmo status — a checagem
        # `payment.status == status` no topo de `process_webhook_event` já
        # devolve cedo, sem sequer tentar renovar de novo.
        result = await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.APROVADO
        )

        assert result is payments.store[payment.id]
        assert subs.store[sub.id].current_period_end == first_period_end
        assert first_period_end > old_period_end
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1

    async def test_aprovado_does_not_reactivate_cancelled_subscription(self, repos):
        """PROMPT 09 do master (Confirmação e ativação) — TESTES AUTO
        'fora de ordem' + 'assinatura cancelada': um evento APROVADO que
        chega atrasado (ex.: o usuário já cancelou a assinatura PENDENTE
        pelo banner de ADR-025, e só depois o webhook do provedor real
        confirma o pagamento que originou aquela PENDENTE) não pode
        reativar uma assinatura que já foi para um estado terminal.

        Verificado por leitura de código (`process_webhook_event`,
        `app/services/billing/payment_service.py`): o ramo `APROVADO` só
        chama `activate_subscription` quando
        `subscription.status == SubscriptionStatus.PENDENTE` — para
        CANCELADA (ou qualquer outro status não-PENDENTE) o evento é
        aplicado ao `Payment` (fica com o status real do provedor,
        correto para auditoria) mas não gera nenhum efeito colateral na
        assinatura. O comportamento já existia antes deste teste; este
        teste só fecha a lacuna de cobertura (não havia nenhum teste
        para o caso 'assinatura já CANCELADA' antes desta sessão).
        """
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.CANCELADA)
        subs.seed(sub)
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.PENDENTE)
        payments.seed(payment)
        service, _ = make_service(repos)

        result = await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.APROVADO
        )

        assert result.status == PaymentStatus.APROVADO
        assert subs.store[sub.id].status == SubscriptionStatus.CANCELADA

    async def test_estornado_marks_subscription_as_inadimplente(self, repos):
        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.APROVADO)
        payments.seed(payment)
        service, _ = make_service(repos)

        await service.process_webhook_event(
            provider_payment_id=payment.provider_payment_id, status=PaymentStatus.ESTORNADO
        )

        assert subs.store[sub.id].status == SubscriptionStatus.INADIMPLENTE

    async def test_rejects_unknown_provider_payment_id(self, repos):
        service, _ = make_service(repos)

        with pytest.raises(NotFoundError):
            await service.process_webhook_event(
                provider_payment_id="does-not-exist", status=PaymentStatus.APROVADO
            )


class TestProcessWebhookEventConcurrency:
    """Roadmap item 7 / ADR-017: a checagem `payment.status == status` no
    topo de `process_webhook_event` cobre reentrega sequencial, mas não
    duas entregas concorrentes lendo o mesmo status antigo antes de
    qualquer uma escrever — mesma forma do achado já corrigido em
    `SubscriptionService.mark_payment_failed`
    (`test_subscription_service.py::TestMarkPaymentFailedConcurrencyFinding`),
    aqui um nível acima: dois eventos RECUSADO concorrentes para o mesmo
    `Payment` não podem chamar `mark_payment_failed` duas vezes.
    """

    async def test_two_concurrent_recusado_events_only_process_once(self, repos):
        import asyncio

        payments, subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)
        payment = make_payment(subscription_id=sub.id, status=PaymentStatus.APROVADO)
        payments.seed(payment)
        service, _ = make_service(repos)

        original_get = payments.get_by_provider_payment_id

        async def get_with_yield(provider_payment_id):
            await asyncio.sleep(0)  # força a outra tarefa a também ler antes de qualquer escrita
            return await original_get(provider_payment_id)

        payments.get_by_provider_payment_id = get_with_yield

        results = await asyncio.gather(
            service.process_webhook_event(
                provider_payment_id=payment.provider_payment_id, status=PaymentStatus.RECUSADO
            ),
            service.process_webhook_event(
                provider_payment_id=payment.provider_payment_id, status=PaymentStatus.RECUSADO
            ),
        )

        assert all(r.status == PaymentStatus.RECUSADO for r in results)
        # A assinatura só pode ter sido processada por
        # `mark_payment_failed` uma vez — se as duas chamadas concorrentes
        # tivessem acionado o efeito colateral, haveria 2 entradas de
        # `SubscriptionHistory` para o mesmo evento de falha (mesma
        # asserção usada para provar a correção em
        # `TestMarkPaymentFailedConcurrencyFinding`).
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert subs.store[sub.id].status == SubscriptionStatus.INADIMPLENTE


class TestListBySubscription:
    async def test_returns_payments_for_subscription(self, repos):
        payments, subs, plans = repos
        sub_id = uuid.uuid4()
        other_sub_id = uuid.uuid4()
        p1 = make_payment(subscription_id=sub_id)
        p2 = make_payment(subscription_id=other_sub_id)
        payments.seed(p1, p2)
        service, _ = make_service(repos)

        result = await service.list_by_subscription(sub_id)

        assert result == [p1]