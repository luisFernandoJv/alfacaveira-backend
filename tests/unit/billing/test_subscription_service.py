"""Testes unitários de `SubscriptionService`.

Usam `FakeSubscriptionRepository`/`FakePlanRepository` (dublês em memória) no
lugar dos repositórios reais, e `FakeAsyncSession` no lugar de uma
`AsyncSession` de verdade — sem banco real, mesmo espírito de
`test_rate_limit_middleware.py` (ver `tests/unit/billing/fakes.py`).

Cobre: criação (agora sempre como PENDENTE, nunca ATIVA diretamente —
incluindo as regras "1 assinatura ativa por usuário" e "1 assinatura
pendente por usuário"), ativação (PENDENTE -> ATIVA), cancelamento
(agendado, imediato, e de assinatura PENDENTE), reativação, renovação,
troca de plano (upgrade/downgrade), falha de pagamento (ramificada por
status de origem) e expiração — a máquina de estados descrita em
`docs/DECISIONS.md` ADR-003/ADR-014 e implementada no PROMPT 05.

Nota de atualização (PROMPT 06): estes testes documentavam, até esta
sessão, o comportamento anterior ao PROMPT 05 (`create_subscription`
retornando `ATIVA` direto, sem estado `PENDENTE`). Atualizados aqui para
refletir `SubscriptionService.activate_subscription` (novo) e a
ramificação de `mark_payment_failed`/`cancel_subscription` por status de
origem — ver `docs/DECISIONS.md` ADR-014 para o detalhamento de cada
decisão. Nenhum teste pré-existente que dependia apenas do caminho `ATIVA`
(troca de plano, renovação, reativação, expiração, achado de corrida em
`mark_payment_failed`) precisou mudar de comportamento esperado.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import BillingPeriod, SubscriptionHistoryReason, SubscriptionStatus
from app.services.billing import subscription_service as subscription_service_module
from app.services.billing.subscription_service import SubscriptionService
from tests.unit.billing.factories import make_plan, make_subscription
from tests.unit.billing.fakes import (
    FakeAsyncSession,
    FakePlanRepository,
    FakeSubscriptionHistoryRepository,
    FakeSubscriptionRepository,
)


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch):
    subs = FakeSubscriptionRepository()
    plans = FakePlanRepository()
    monkeypatch.setattr(subscription_service_module, "SubscriptionRepository", lambda session: subs)
    monkeypatch.setattr(subscription_service_module, "PlanRepository", lambda session: plans)
    # ADR-023: `SubscriptionHistoryRepository` real é substituído pelo fake,
    # que lê de `session.added` (ver docstring de `FakeSubscriptionHistoryRepository`)
    # — por isso não precisa de `.seed()` nem é retornado por esta fixture.
    monkeypatch.setattr(
        subscription_service_module,
        "SubscriptionHistoryRepository",
        FakeSubscriptionHistoryRepository,
    )
    return subs, plans


@pytest.fixture
def service(repos) -> SubscriptionService:
    return SubscriptionService(FakeAsyncSession())


class TestCreateSubscription:
    async def test_creates_pending_subscription_and_history_entry(self, repos, service):
        """PROMPT 05 / ADR-014: `create_subscription` nasce PENDENTE, nunca
        ATIVA diretamente — só `activate_subscription` move para ATIVA, e só
        a partir de confirmação de pagamento via webhook."""
        subs, plans = repos
        plan = make_plan()
        plans.seed(plan)
        user_id = uuid.uuid4()

        subscription = await service.create_subscription(user_id, plan.id)

        assert subscription.status == SubscriptionStatus.PENDENTE
        assert subscription.plan_id == plan.id
        assert subscription.user_id == user_id
        # Placeholder de largura zero (ADR-014, decisão 1): período real só
        # é definido em `activate_subscription`.
        assert subscription.current_period_start == subscription.current_period_end
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert history_entries[0].reason == SubscriptionHistoryReason.CRIADA
        assert history_entries[0].from_status is None
        assert history_entries[0].to_status == SubscriptionStatus.PENDENTE

    async def test_rejects_second_active_subscription_for_same_user(self, repos, service):
        subs, plans = repos
        plan = make_plan()
        plans.seed(plan)
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan, status=SubscriptionStatus.ATIVA))

        with pytest.raises(ConflictError):
            await service.create_subscription(user_id, plan.id)

    async def test_rejects_second_pending_subscription_for_same_user(self, repos, service):
        """Novo no PROMPT 05 (ADR-014, decisão 4): só checagem aplicativa,
        sem índice único de banco equivalente ao de ATIVA — mas o service
        deve rejeitar mesmo assim."""
        subs, plans = repos
        plan = make_plan()
        plans.seed(plan)
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan, status=SubscriptionStatus.PENDENTE))

        with pytest.raises(ConflictError):
            await service.create_subscription(user_id, plan.id)

    async def test_rejects_unknown_plan(self, repos, service):
        with pytest.raises(NotFoundError):
            await service.create_subscription(uuid.uuid4(), uuid.uuid4())

    async def test_rejects_inactive_plan(self, repos, service):
        subs, plans = repos
        plan = make_plan(is_active=False)
        plans.seed(plan)

        with pytest.raises(NotFoundError):
            await service.create_subscription(uuid.uuid4(), plan.id)


class TestActivateSubscription:
    """Novo no PROMPT 05 (ADR-014): `activate_subscription` é a única porta
    de entrada para PENDENTE -> ATIVA, chamada por
    `PaymentService.process_webhook_event` quando o webhook confirma
    APROVADO — nunca a partir do resultado síncrono de `charge_subscription`."""

    async def test_moves_pending_to_ativa_and_sets_real_period(self, repos, service):
        subs, plans = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        sub = make_subscription(status=SubscriptionStatus.PENDENTE, plan=plan)
        # Simula o placeholder de largura zero gravado por create_subscription.
        sub.current_period_start = sub.current_period_end
        subs.seed(sub)

        result = await service.activate_subscription(sub.id)

        assert result.status == SubscriptionStatus.ATIVA
        assert result.current_period_end > result.current_period_start
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert history_entries[-1].reason == SubscriptionHistoryReason.ATIVADA
        assert history_entries[-1].from_status == SubscriptionStatus.PENDENTE
        assert history_entries[-1].to_status == SubscriptionStatus.ATIVA

    async def test_rejects_activation_of_unknown_subscription(self, repos, service):
        with pytest.raises(NotFoundError):
            await service.activate_subscription(uuid.uuid4())

    async def test_rejects_activation_of_non_pending_subscription(self, repos, service):
        """Estado genuinamente inválido para ativar (nunca foi PENDENTE
        aguardando este pagamento) continua levantando ConflictError —
        CANCELADA, não ATIVA (ver teste seguinte para o caso ATIVA, que
        desde ADR-018 é idempotente, não erro)."""
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.CANCELADA)
        subs.seed(sub)

        with pytest.raises(ConflictError):
            await service.activate_subscription(sub.id)

    async def test_activation_of_already_active_subscription_is_idempotent(
        self, repos, service
    ):
        """Corrigido nesta sessão (roadmap item 7, ADR-018 — achado real via
        teste de concorrência contra Postgres): reenvio de webhook APROVADO
        para uma assinatura já ATIVA (reentrega, ou dois Payments distintos
        vencendo cada um o próprio CAS) não deve levantar ConflictError —
        deve devolver o estado atual sem duplicar SubscriptionHistory nem
        sobrescrever o período já gravado pela chamada vencedora. Mesmo
        padrão de `mark_payment_failed` (ADR-017) e `expire_subscription`
        (ADR-018)."""
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        result = await service.activate_subscription(sub.id)

        assert result.status == SubscriptionStatus.ATIVA
        assert result is sub
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert history_entries == []


class TestCancelSubscription:
    async def test_scheduled_cancel_keeps_status_active(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        result = await service.cancel_subscription(sub.id, sub.user_id, immediately=False)

        assert result.status == SubscriptionStatus.ATIVA
        assert result.cancel_at_period_end is True

    async def test_immediate_cancel_sets_status_cancelled(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        result = await service.cancel_subscription(sub.id, sub.user_id, immediately=True)

        assert result.status == SubscriptionStatus.CANCELADA
        assert result.cancel_at_period_end is True

    async def test_rejects_cancel_of_non_active_subscription(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.CANCELADA)
        subs.seed(sub)

        with pytest.raises(ConflictError):
            await service.cancel_subscription(sub.id, sub.user_id)

    async def test_rejects_cancel_of_subscription_not_owned_by_user(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        with pytest.raises(NotFoundError):
            await service.cancel_subscription(sub.id, uuid.uuid4())

    async def test_cancel_of_pending_subscription_is_always_immediate(self, repos, service):
        """Novo no PROMPT 05 (ADR-014, decisão 3): PENDENTE cancela na hora
        sempre, ignorando `immediately` — não existe "fim de período" para
        uma assinatura que nunca chegou a cobrar."""
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.PENDENTE)
        subs.seed(sub)

        result = await service.cancel_subscription(sub.id, sub.user_id, immediately=False)

        assert result.status == SubscriptionStatus.CANCELADA
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert history_entries[-1].from_status == SubscriptionStatus.PENDENTE
        assert history_entries[-1].to_status == SubscriptionStatus.CANCELADA


class TestReactivateSubscription:
    async def test_undoes_scheduled_cancellation(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA, cancel_at_period_end=True)
        subs.seed(sub)

        result = await service.reactivate_subscription(sub.id, sub.user_id)

        assert result.cancel_at_period_end is False
        assert result.status == SubscriptionStatus.ATIVA

    async def test_rejects_when_status_is_not_ativa(self, repos, service):
        """Genuinamente inválido: cancelada/pendente/etc não têm
        `cancel_at_period_end` para desfazer."""
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.CANCELADA)
        subs.seed(sub)

        with pytest.raises(ConflictError):
            await service.reactivate_subscription(sub.id, sub.user_id)

    async def test_reactivation_when_not_scheduled_is_idempotent(self, repos, service):
        """Corrigido nesta sessão (ADR-021, opção (a)): ATIVA sem
        cancelamento agendado — seja porque nunca foi agendado, seja porque
        uma chamada concorrente já reativou — devolve o estado atual em vez
        de ConflictError. Ver docstring de `reactivate_subscription` para a
        justificativa de não distinguir os dois casos."""
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA, cancel_at_period_end=False)
        subs.seed(sub)

        result = await service.reactivate_subscription(sub.id, sub.user_id)

        assert result.status == SubscriptionStatus.ATIVA
        assert result.cancel_at_period_end is False
        assert result is sub


class TestRenewSubscription:
    async def test_advances_current_period_by_plan_length(self, repos, service):
        subs, plans = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan)
        subs.seed(sub)
        old_end = sub.current_period_end

        result = await service.renew_subscription(sub.id, sub.user_id, uuid.uuid4())

        assert result.current_period_start == old_end
        assert result.current_period_end > old_end

    async def test_rejects_renew_of_non_active_subscription(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.EXPIRADA)
        subs.seed(sub)

        with pytest.raises(ConflictError):
            await service.renew_subscription(sub.id, sub.user_id, uuid.uuid4())

    async def test_repeated_payment_id_is_idempotent_no_op(self, repos, service):
        """ADR-023 (resolvendo o achado do ADR-022): uma segunda chamada
        com o MESMO `payment_id` — reentrega do mesmo evento de pagamento —
        não avança o período uma segunda vez."""
        subs, plans = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan)
        subs.seed(sub)
        old_end = sub.current_period_end
        payment_id = uuid.uuid4()

        first = await service.renew_subscription(sub.id, sub.user_id, payment_id)
        first_end = first.current_period_end
        second = await service.renew_subscription(sub.id, sub.user_id, payment_id)

        assert first_end > old_end
        assert second.current_period_end == first_end
        history_entries = [
            e for e in service._session.added if getattr(e, "payment_id", None) == payment_id
        ]
        assert len(history_entries) == 1

    async def test_different_payment_id_applies_a_new_renewal(self, repos, service):
        """Um `payment_id` novo é uma renovação legítima e distinta —
        avança o período de novo (não deve ser confundido com reentrega)."""
        subs, plans = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan)
        subs.seed(sub)
        old_end = sub.current_period_end

        first = await service.renew_subscription(sub.id, sub.user_id, uuid.uuid4())
        first_end = first.current_period_end
        second = await service.renew_subscription(sub.id, sub.user_id, uuid.uuid4())

        assert first_end > old_end
        assert second.current_period_end > first_end
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 2


class TestChangePlan:
    async def test_upgrade_when_new_plan_is_more_expensive(self, repos, service):
        subs, plans = repos
        old_plan = make_plan(slug="standard", price_cents=1000)
        new_plan = make_plan(slug="pro", price_cents=5000)
        plans.seed(old_plan, new_plan)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=old_plan)
        subs.seed(sub)

        result = await service.change_plan(sub.id, sub.user_id, new_plan.id)

        assert result.plan_id == new_plan.id
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert history_entries[-1].reason == SubscriptionHistoryReason.UPGRADE

    async def test_downgrade_when_new_plan_is_cheaper(self, repos, service):
        subs, plans = repos
        old_plan = make_plan(slug="pro", price_cents=5000)
        new_plan = make_plan(slug="standard", price_cents=1000)
        plans.seed(old_plan, new_plan)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=old_plan)
        subs.seed(sub)

        result = await service.change_plan(sub.id, sub.user_id, new_plan.id)

        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert history_entries[-1].reason == SubscriptionHistoryReason.DOWNGRADE
        assert result.plan_id == new_plan.id

    async def test_rejects_change_to_same_plan(self, repos, service):
        subs, plans = repos
        plan = make_plan()
        plans.seed(plan)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan)
        subs.seed(sub)

        with pytest.raises(ConflictError):
            await service.change_plan(sub.id, sub.user_id, plan.id)

    async def test_rejects_change_to_unknown_plan(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        with pytest.raises(NotFoundError):
            await service.change_plan(sub.id, sub.user_id, uuid.uuid4())

    async def test_repeated_sequential_call_to_same_target_plan_raises_not_duplicates(
        self, repos, service
    ):
        """ADR-023 (análise do achado do ADR-022 para `change_plan`): uma
        segunda chamada sequencial (não concorrente) para o MESMO
        plano-alvo, depois que a primeira já comitou, não duplica
        `SubscriptionHistory` — ela cai no guard "já está neste plano" e
        falha explicitamente, em vez de reaplicar silenciosamente."""
        subs, plans = repos
        old_plan = make_plan(slug="standard", price_cents=1000)
        new_plan = make_plan(slug="pro", price_cents=5000)
        plans.seed(old_plan, new_plan)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=old_plan)
        subs.seed(sub)

        first = await service.change_plan(sub.id, sub.user_id, new_plan.id)
        assert first.plan_id == new_plan.id

        with pytest.raises(ConflictError):
            await service.change_plan(sub.id, sub.user_id, new_plan.id)

        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1

    async def test_change_to_a_different_plan_after_a_prior_change_still_applies(
        self, repos, service
    ):
        """Duas trocas sequenciais e legítimas para plano-alvos DIFERENTES
        continuam permitidas (não é o mesmo caso do teste acima) — ver
        ADR-023 para por que este caso específico permanece sem proteção
        adicional além do CAS (indistinguível de uma correção genuína do
        usuário sem uma chave de evento que o endpoint não recebe hoje)."""
        subs, plans = repos
        plan_a = make_plan(slug="standard", price_cents=1000)
        plan_b = make_plan(slug="pro", price_cents=5000)
        plan_c = make_plan(slug="premium", price_cents=9000)
        plans.seed(plan_a, plan_b, plan_c)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan_a)
        subs.seed(sub)

        first = await service.change_plan(sub.id, sub.user_id, plan_b.id)
        assert first.plan_id == plan_b.id

        second = await service.change_plan(sub.id, sub.user_id, plan_c.id)
        assert second.plan_id == plan_c.id

        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 2


class TestMarkPaymentFailed:
    async def test_moves_subscription_to_inadimplente(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        result = await service.mark_payment_failed(sub.id)

        assert result.status == SubscriptionStatus.INADIMPLENTE
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert history_entries[-1].reason == SubscriptionHistoryReason.PAGAMENTO_FALHOU

    async def test_moves_pending_subscription_to_cancelada(self, repos, service):
        """Novo no PROMPT 05 (ADR-014, decisão 2): se a origem é PENDENTE
        (falha do pagamento de ativação), o destino é CANCELADA, não
        INADIMPLENTE — nunca existiu uma assinatura paga para ficar
        inadimplente. O caso de origem ATIVA (acima) não muda."""
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.PENDENTE)
        subs.seed(sub)

        result = await service.mark_payment_failed(sub.id)

        assert result.status == SubscriptionStatus.CANCELADA
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert history_entries[-1].reason == SubscriptionHistoryReason.PAGAMENTO_FALHOU
        assert history_entries[-1].from_status == SubscriptionStatus.PENDENTE
        assert history_entries[-1].to_status == SubscriptionStatus.CANCELADA

    async def test_rejects_unknown_subscription(self, repos, service):
        with pytest.raises(NotFoundError):
            await service.mark_payment_failed(uuid.uuid4())


class TestExpireSubscription:
    async def test_moves_active_subscription_to_expirada(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        result = await service.expire_subscription(sub.id)

        assert result.status == SubscriptionStatus.EXPIRADA

    async def test_rejects_expiring_non_active_subscription(self, repos, service):
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.CANCELADA)
        subs.seed(sub)

        with pytest.raises(ConflictError):
            await service.expire_subscription(sub.id)


class TestMarkPaymentFailedConcurrencyFinding:
    """Cobre a correção (roadmap item 7, ADR-017) do achado que era só
    documentado até o PROMPT 06: leitura seguida de escrita sem
    lock/versão permitia que duas entregas concorrentes do mesmo evento
    processassem a falha de pagamento simultaneamente
    (`docs/DECISIONS.md`, "Risco registrado — possível corrida em
    `mark_payment_failed`"; `docs/HANDOFF.md` §7.1 de sessões anteriores).

    O teste força as duas chamadas a lerem a assinatura antes de
    qualquer uma escrever (`asyncio.sleep(0)` dentro do fake de leitura,
    simulando o ponto exato em que duas entregas de webhook
    intercalariam num ambiente real com I/O de banco entre leitura e
    escrita) — exatamente a mesma técnica usada para demonstrar o achado
    originalmente. A diferença é a asserção: agora que a escrita passa
    por `compare_and_swap_status`, só uma das duas chamadas deve
    conseguir gravar.
    """

    async def test_two_concurrent_calls_only_one_processes_the_failure(self, repos, service):
        import asyncio

        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        original_get_by_id = subs.get_by_id

        async def get_by_id_with_yield(subscription_id):
            await asyncio.sleep(0)  # força a outra tarefa a também ler antes de qualquer escrita
            return await original_get_by_id(subscription_id)

        subs.get_by_id = get_by_id_with_yield

        results = await asyncio.gather(
            service.mark_payment_failed(sub.id),
            service.mark_payment_failed(sub.id),
        )

        # As duas chamadas leram a assinatura ainda ATIVA antes de qualquer
        # escrita (mesma condição de corrida de antes), mas agora só uma
        # delas vence o `compare_and_swap_status` — a outra perde o CAS,
        # não grava histórico e devolve o estado já atualizado pela
        # vencedora (idempotente).
        assert all(r.status == SubscriptionStatus.INADIMPLENTE for r in results)
        assert subs.store[sub.id].status == SubscriptionStatus.INADIMPLENTE
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert history_entries[0].reason == SubscriptionHistoryReason.PAGAMENTO_FALHOU
        assert history_entries[0].from_status == SubscriptionStatus.ATIVA
        assert history_entries[0].to_status == SubscriptionStatus.INADIMPLENTE

    async def test_is_idempotent_when_already_in_terminal_status(self, repos, service):
        """Corrigido junto com a corrida nesta sessão (ADR-017): chamar
        `mark_payment_failed` para uma assinatura que já não está em
        PENDENTE/ATIVA (ex.: já INADIMPLENTE por uma entrega anterior, ou
        já CANCELADA/EXPIRADA) não grava mais nada — antes desta sessão
        isso não era checado e a assinatura seria movida para
        INADIMPLENTE incondicionalmente, mesmo partindo de, por exemplo,
        EXPIRADA."""
        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.INADIMPLENTE)
        subs.seed(sub)

        result = await service.mark_payment_failed(sub.id)

        assert result.status == SubscriptionStatus.INADIMPLENTE
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert history_entries == []


class TestActivateSubscriptionConcurrency:
    """Roadmap item 7 / ADR-018 (esta sessão): estende a proteção de
    `compare_and_swap_status` a `activate_subscription`, além de
    `mark_payment_failed` (ADR-017). O cenário aqui não é reentrega do
    mesmo webhook (isso já é filtrado pelo CAS de `Payment` em
    `PaymentService.process_webhook_event` antes de chamar isto), e sim
    dois `Payment` distintos para a mesma assinatura chegando quase
    juntos — ex.: cobrança duplicada por duplo-clique em
    `charge_subscription`, cada um com seu próprio `provider_payment_id`
    e cada um já tendo vencido o CAS do seu próprio `Payment`."""

    async def test_two_concurrent_calls_only_one_activates(self, repos, service):
        """A leitura em si (`get_by_id_with_plan`) não tem ponto de
        suspensão real no dublê, então as duas chamadas leem o mesmo
        PENDENTE de forma síncrona antes de qualquer escrita — o ponto
        exato em que duas entregas concorrentes divergem num ambiente
        real é a escrita (`compare_and_swap_status`), por isso o
        `asyncio.sleep(0)` é injetado ali, não na leitura (diferente de
        `TestMarkPaymentFailedConcurrencyFinding`, cujo yield na leitura
        já basta porque o guard inicial daquele método trata qualquer
        status inesperado como idempotente, não como erro — aqui o guard
        de `activate_subscription` levanta `ConflictError` para não-
        PENDENTE, então só o yield no CAS isola de fato a corrida real
        sem disparar esse guard por engano)."""
        import asyncio

        subs, plans = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        sub = make_subscription(status=SubscriptionStatus.PENDENTE, plan=plan)
        sub.current_period_start = sub.current_period_end
        subs.seed(sub)

        original_cas = subs.compare_and_swap_status

        async def cas_with_yield(*args, **kwargs):
            # força as duas chamadas a chegarem no CAS antes de qualquer escrita
            await asyncio.sleep(0)
            return await original_cas(*args, **kwargs)

        subs.compare_and_swap_status = cas_with_yield

        results = await asyncio.gather(
            service.activate_subscription(sub.id),
            service.activate_subscription(sub.id),
        )

        assert all(r.status == SubscriptionStatus.ATIVA for r in results)
        assert subs.store[sub.id].status == SubscriptionStatus.ATIVA
        # As duas chamadas devolvem o mesmo período (o gravado pela
        # vencedora do CAS) — a perdedora não sobrescreve com o seu.
        assert results[0].current_period_start == results[1].current_period_start
        assert results[0].current_period_end == results[1].current_period_end
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert history_entries[0].reason == SubscriptionHistoryReason.ATIVADA

    async def test_loser_does_not_raise_conflict_error(self, repos, service):
        """A chamada que perde o CAS trata a corrida como idempotente
        (devolve o estado ATIVA atual), não levanta `ConflictError` — a
        checagem de status feita na leitura inicial já passou como
        PENDENTE para ambas as chamadas; só a escrita decide quem vence."""
        import asyncio

        subs, plans = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        sub = make_subscription(status=SubscriptionStatus.PENDENTE, plan=plan)
        subs.seed(sub)

        original_cas = subs.compare_and_swap_status

        async def cas_with_yield(*args, **kwargs):
            await asyncio.sleep(0)
            return await original_cas(*args, **kwargs)

        subs.compare_and_swap_status = cas_with_yield

        # Nenhuma das duas deve levantar ConflictError.
        results = await asyncio.gather(
            service.activate_subscription(sub.id),
            service.activate_subscription(sub.id),
            return_exceptions=True,
        )
        assert not any(isinstance(r, Exception) for r in results)


class TestExpireSubscriptionConcurrency:
    """Roadmap item 7 / ADR-018 (esta sessão): `expire_subscription` é
    acionada por job agendado, não por request de usuário —
    `PROJECT_STATE.md` §16 já registra "evitar jobs duplicados em
    múltiplas instâncias" como pendência antes de escalar a API
    horizontalmente, o que torna duas execuções concorrentes um cenário
    plausível (não só teórico) para este método em particular."""

    async def test_two_concurrent_calls_only_one_expires(self, repos, service):
        """Mesma técnica de `TestActivateSubscriptionConcurrency`: o yield
        vai no CAS, não na leitura (`get_by_id` no dublê não tem ponto de
        suspensão real, e o guard inicial de `expire_subscription`
        levanta `ConflictError` para não-ATIVA — um yield só na leitura
        faria a segunda chamada, ao resumir depois da primeira já ter
        escrito, ler EXPIRADA e cair nesse guard em vez de exercitar o
        CAS de fato)."""
        import asyncio

        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        original_cas = subs.compare_and_swap_status

        async def cas_with_yield(*args, **kwargs):
            await asyncio.sleep(0)
            return await original_cas(*args, **kwargs)

        subs.compare_and_swap_status = cas_with_yield

        results = await asyncio.gather(
            service.expire_subscription(sub.id),
            service.expire_subscription(sub.id),
        )

        assert all(r.status == SubscriptionStatus.EXPIRADA for r in results)
        assert subs.store[sub.id].status == SubscriptionStatus.EXPIRADA
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert history_entries[0].reason == SubscriptionHistoryReason.EXPIRADA


class TestConcurrencyGeneralizedCas:
    """Cobre a generalização de `compare_and_swap_status` para
    `compare_and_swap` (ADR-019) aplicada a `cancel_subscription`,
    `reactivate_subscription`, `renew_subscription` e `change_plan` — as
    quatro escritas que o ADR-018 avaliou e conscientemente deixou sem
    CAS por não serem transições de *apenas* status. Mesma técnica de
    reprodução determinística das classes acima: `asyncio.sleep(0)`
    injetado no dublê de `compare_and_swap` (não no de leitura), pelo
    mesmo motivo já documentado em `TestActivateSubscriptionConcurrency`
    — o guard de pré-condição no topo de cada método levantaria
    `ConflictError`/devolveria estado inesperado se a segunda chamada,
    ao retomar, já lesse o valor pós-escrita da primeira.
    """

    async def test_cancel_two_concurrent_calls_only_one_cancels(self, repos, service):
        import asyncio

        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA)
        subs.seed(sub)

        original_cas = subs.compare_and_swap

        async def cas_with_yield(*args, **kwargs):
            await asyncio.sleep(0)
            return await original_cas(*args, **kwargs)

        subs.compare_and_swap = cas_with_yield

        results = await asyncio.gather(
            service.cancel_subscription(sub.id, sub.user_id, immediately=True),
            service.cancel_subscription(sub.id, sub.user_id, immediately=True),
        )

        assert all(r.status == SubscriptionStatus.CANCELADA for r in results)
        assert subs.store[sub.id].status == SubscriptionStatus.CANCELADA
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert history_entries[0].reason == SubscriptionHistoryReason.CANCELADA

    async def test_reactivate_two_concurrent_calls_only_one_reactivates(self, repos, service):
        import asyncio

        subs, plans = repos
        sub = make_subscription(status=SubscriptionStatus.ATIVA, cancel_at_period_end=True)
        subs.seed(sub)

        original_cas = subs.compare_and_swap

        async def cas_with_yield(*args, **kwargs):
            await asyncio.sleep(0)
            return await original_cas(*args, **kwargs)

        subs.compare_and_swap = cas_with_yield

        results = await asyncio.gather(
            service.reactivate_subscription(sub.id, sub.user_id),
            service.reactivate_subscription(sub.id, sub.user_id),
        )

        assert all(r.cancel_at_period_end is False for r in results)
        assert subs.store[sub.id].cancel_at_period_end is False
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert history_entries[0].reason == SubscriptionHistoryReason.REATIVADA

    async def test_renew_two_concurrent_calls_only_one_advances_period(self, repos, service):
        import asyncio

        subs, plans = repos
        plan = make_plan(billing_period=BillingPeriod.MENSAL)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=plan)
        subs.seed(sub)
        old_end = sub.current_period_end

        original_cas = subs.compare_and_swap

        async def cas_with_yield(*args, **kwargs):
            await asyncio.sleep(0)
            return await original_cas(*args, **kwargs)

        subs.compare_and_swap = cas_with_yield

        payment_id = uuid.uuid4()
        results = await asyncio.gather(
            service.renew_subscription(sub.id, sub.user_id, payment_id),
            service.renew_subscription(sub.id, sub.user_id, payment_id),
        )

        # A corrida não pode fazer o período avançar duas vezes: as duas
        # chamadas leram o mesmo `old_end` (mesmo ponto de partida), mas
        # só a vencedora do CAS grava — se a segunda não perdesse o CAS,
        # o período teria avançado 2x o comprimento do plano em vez de 1x.
        assert all(r.current_period_start == old_end for r in results)
        assert all(r.current_period_end == subs.store[sub.id].current_period_end for r in results)
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1
        assert history_entries[0].reason == SubscriptionHistoryReason.RENOVADA

    async def test_change_plan_two_concurrent_calls_only_one_applies(self, repos, service):
        import asyncio

        subs, plans = repos
        old_plan = make_plan(slug="standard", price_cents=1000)
        new_plan = make_plan(slug="pro", price_cents=5000)
        plans.seed(old_plan, new_plan)
        sub = make_subscription(status=SubscriptionStatus.ATIVA, plan=old_plan)
        subs.seed(sub)

        original_cas = subs.compare_and_swap

        async def cas_with_yield(*args, **kwargs):
            await asyncio.sleep(0)
            return await original_cas(*args, **kwargs)

        subs.compare_and_swap = cas_with_yield

        results = await asyncio.gather(
            service.change_plan(sub.id, sub.user_id, new_plan.id),
            service.change_plan(sub.id, sub.user_id, new_plan.id),
        )

        assert all(r.plan_id == new_plan.id for r in results)
        assert subs.store[sub.id].plan_id == new_plan.id
        history_entries = [e for e in service._session.added if hasattr(e, "reason")]
        assert len(history_entries) == 1