"""Concorrência real contra Postgres para os 7 métodos de `Subscription`
protegidos por `compare_and_swap`/`compare_and_swap_status`
(ADR-017 + ADR-018 + ADR-019), fechando o gap que `tests/unit/billing/
test_subscription_service.py` deixava (dublê determinístico, não banco
real — ver docs/HANDOFF.md, pendência 5, e PROMPT desta sessão).

EXECUTADO contra Postgres real (via `apt`, não Docker) na sessão que
corrigiu o achado do ADR-022 (ver docs/HANDOFF.md e
docs/IMPLEMENTATION_LOG.md para os resultados exatos) — a nota "NÃO
EXECUTADO NESTA SESSÃO" de uma versão anterior deste arquivo estava
desatualizada e foi removida. `TestRenewSubscriptionConcurrencyReal` foi
reescrita nesta sessão (ADR-023) para cobrir `payment_id`; as demais
classes continuam validando exatamente o que já validavam.

Reaproveita exatamente as mesmas asserções de comportamento já validadas
em `tests/unit/billing/test_subscription_service.py` (classes
`TestConcurrencyGeneralizedCas`, `TestActivateSubscriptionConcurrency`,
`TestExpireSubscriptionConcurrency`) — aqui só trocamos o dublê por duas
conexões reais e concorrentes contra a mesma linha:
- quem perde o CAS não levanta erro adicional (nem `ConflictError`, nem
  exceção do driver);
- não duplica `SubscriptionHistory`;
- o estado final é o gravado pela chamada vencedora, nunca uma mistura.

Padrão de concorrência usado em cada teste: duas `AsyncSession`
independentes (cada uma sua própria conexão do `db_engine`, não
`db_session` — que roda dentro de uma única transação externa e não serve
para simular duas transações committadas de verdade) carregam a mesma
`Subscription`, e então `asyncio.gather` dispara as duas chamadas de
service "ao mesmo tempo" — sob READ COMMITTED, a segunda `UPDATE` só
libera depois que a primeira commita, e reavalia o `WHERE` contra o valor
já commitado (mesmo raciocínio documentado na docstring de
`compare_and_swap` em `subscription_repository.py`).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.billing.payment import Payment
from app.models.billing.plan import Plan
from app.models.billing.subscription import Subscription
from app.models.billing.subscription_history import SubscriptionHistory
from app.models.enums import BillingPeriod, PaymentStatus, SubscriptionStatus
from app.models.identity.user import User
from app.services.billing.subscription_service import SubscriptionService

pytestmark = pytest.mark.asyncio


def _session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Uma sessão por chamada = uma transação independente e committada de
    verdade — não reaproveitar `db_session` aqui (ver docstring do módulo).
    """
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


async def _seed_user_plan_subscription(
    session: AsyncSession,
    *,
    status: SubscriptionStatus = SubscriptionStatus.ATIVA,
    cancel_at_period_end: bool = False,
    billing_period: BillingPeriod = BillingPeriod.MENSAL,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Cria User + Plan + Subscription mínimos direto no banco real (sem
    passar pelos services — queremos só a linha existente para disputar).
    Retorna (user_id, subscription_id, plan_id).
    """
    now = datetime.now(UTC)
    user = User(
        email=f"{uuid.uuid4()}@teste.local",
        password_hash="hash-nao-usado-neste-teste",
        full_name="Usuário de Teste de Concorrência",
        is_active=True,
    )
    plan = Plan(
        name="Plano de Teste",
        slug=f"plano-teste-{uuid.uuid4()}",
        price_cents=9990,
        billing_period=billing_period,
        features={},
        is_active=True,
    )
    session.add_all([user, plan])
    await session.flush()

    subscription = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=status,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        cancel_at_period_end=cancel_at_period_end,
    )
    session.add(subscription)
    await session.commit()
    return user.id, subscription.id, plan.id


async def _seed_payment(session: AsyncSession, subscription_id: uuid.UUID) -> uuid.UUID:
    """`renew_subscription` exige um `payment_id` que referencie um
    `Payment` real (FK da migration 0008) — usar `uuid.uuid4()` solto (sem
    linha correspondente em `payments`) viola a FK contra Postgres real
    (achado desta sessão: o `except IntegrityError` antigo em
    `SubscriptionService.renew_subscription` engolia essa violação
    silenciosamente, mascarando-a como se fosse a corrida do índice único
    — ver ADR-023, correção pós-rerun). Cada teste de renovação deve
    seedar um `Payment` por chamada e usar `payment.id` aqui.
    """
    payment = Payment(
        subscription_id=subscription_id,
        amount_cents=9990,
        currency="BRL",
        status=PaymentStatus.APROVADO,
    )
    session.add(payment)
    await session.commit()
    return payment.id


async def _history_count(session: AsyncSession, subscription_id: uuid.UUID) -> int:
    stmt = select(SubscriptionHistory).where(SubscriptionHistory.subscription_id == subscription_id)
    result = await session.execute(stmt)
    return len(result.scalars().all())


class TestCancelSubscriptionConcurrencyReal:
    async def test_two_concurrent_cancels_only_one_history_entry(self, db_engine: AsyncEngine) -> None:
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            user_id, subscription_id, _ = await _seed_user_plan_subscription(seed_session)

        async with factory() as s1, factory() as s2:
            service_a = SubscriptionService(s1)
            service_b = SubscriptionService(s2)
            results = await asyncio.gather(
                service_a.cancel_subscription(subscription_id, user_id, immediately=True),
                service_b.cancel_subscription(subscription_id, user_id, immediately=True),
                return_exceptions=True,
            )

        for result in results:
            assert not isinstance(result, Exception), result

        async with factory() as check_session:
            assert await _history_count(check_session, subscription_id) == 1
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None
            assert subscription.status == SubscriptionStatus.CANCELADA


class TestReactivateSubscriptionConcurrencyReal:
    async def test_two_concurrent_reactivations_only_one_history_entry(
        self, db_engine: AsyncEngine
    ) -> None:
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            user_id, subscription_id, _ = await _seed_user_plan_subscription(
                seed_session, cancel_at_period_end=True
            )

        async with factory() as s1, factory() as s2:
            service_a = SubscriptionService(s1)
            service_b = SubscriptionService(s2)
            results = await asyncio.gather(
                service_a.reactivate_subscription(subscription_id, user_id),
                service_b.reactivate_subscription(subscription_id, user_id),
                return_exceptions=True,
            )

        for result in results:
            assert not isinstance(result, Exception), result

        async with factory() as check_session:
            assert await _history_count(check_session, subscription_id) == 1
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None
            assert subscription.cancel_at_period_end is False


class TestRenewSubscriptionConcurrencyReal:
    async def test_two_concurrent_renewals_with_same_payment_id_advance_period_only_once(
        self, db_engine: AsyncEngine
    ) -> None:
        """ADR-023 (resolvendo o achado do ADR-022): reproduz exatamente o
        cenário que falhava antes desta sessão (ver docs/IMPLEMENTATION_LOG.md)
        — duas chamadas verdadeiramente concorrentes, agora com o MESMO
        `payment_id` (reentrega do mesmo evento de pagamento, ex.: webhook
        duplicado). Antes do ADR-023, isto produzia 2 entradas de
        `SubscriptionHistory` e o período avançava 60 dias em vez de 30."""
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            user_id, subscription_id, _ = await _seed_user_plan_subscription(seed_session)
            original = await seed_session.get(Subscription, subscription_id)
            assert original is not None
            original_end = original.current_period_end

        async with factory() as payment_session:
            payment_id = await _seed_payment(payment_session, subscription_id)

        async with factory() as s1, factory() as s2:
            service_a = SubscriptionService(s1)
            service_b = SubscriptionService(s2)
            results = await asyncio.gather(
                service_a.renew_subscription(subscription_id, user_id, payment_id),
                service_b.renew_subscription(subscription_id, user_id, payment_id),
                return_exceptions=True,
            )

        for result in results:
            assert not isinstance(result, Exception), result

        async with factory() as check_session:
            assert await _history_count(check_session, subscription_id) == 1
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None
            # Avançou exatamente 30 dias (1x), não 60 (2x) — é a asserção
            # que só faz sentido contra concorrência real: sob o dublê em
            # memória as duas leituras nunca competem de fato pela mesma
            # linha no mesmo instante.
            assert subscription.current_period_end == original_end + timedelta(days=30)

    async def test_sequential_renewal_with_same_payment_id_is_idempotent(
        self, db_engine: AsyncEngine
    ) -> None:
        """Não-concorrente: a segunda chamada só começa depois que a
        primeira já commitou por completo — cenário exato descrito no
        ADR-022 ("leitura acontece depois do commit alheio"), que o CAS
        sozinho NÃO protege (a segunda leitura já vê o período avançado
        como sua própria baseline e o CAS bateria normalmente). Só a
        checagem de `payment_id` evita a duplicação aqui."""
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            user_id, subscription_id, _ = await _seed_user_plan_subscription(seed_session)
            original = await seed_session.get(Subscription, subscription_id)
            assert original is not None
            original_end = original.current_period_end

        async with factory() as payment_session:
            payment_id = await _seed_payment(payment_session, subscription_id)

        async with factory() as s1:
            await SubscriptionService(s1).renew_subscription(subscription_id, user_id, payment_id)
        async with factory() as s2:
            await SubscriptionService(s2).renew_subscription(subscription_id, user_id, payment_id)

        async with factory() as check_session:
            assert await _history_count(check_session, subscription_id) == 1
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None
            assert subscription.current_period_end == original_end + timedelta(days=30)

    async def test_sequential_renewal_with_different_payment_id_applies_again(
        self, db_engine: AsyncEngine
    ) -> None:
        """Controle negativo do teste acima: um `payment_id` NOVO é uma
        renovação legítima e distinta — não deve ser confundida com
        reentrega. Protege contra uma implementação "idempotente demais"
        que bloquearia renovações reais subsequentes."""
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            user_id, subscription_id, _ = await _seed_user_plan_subscription(seed_session)
            original = await seed_session.get(Subscription, subscription_id)
            assert original is not None
            original_end = original.current_period_end

        async with factory() as payment_session:
            payment_id_1 = await _seed_payment(payment_session, subscription_id)
        async with factory() as payment_session:
            payment_id_2 = await _seed_payment(payment_session, subscription_id)

        async with factory() as s1:
            await SubscriptionService(s1).renew_subscription(subscription_id, user_id, payment_id_1)
        async with factory() as s2:
            await SubscriptionService(s2).renew_subscription(subscription_id, user_id, payment_id_2)

        async with factory() as check_session:
            assert await _history_count(check_session, subscription_id) == 2
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None
            assert subscription.current_period_end == original_end + timedelta(days=60)


class TestChangePlanConcurrencyReal:
    async def test_two_concurrent_plan_changes_only_one_wins(self, db_engine: AsyncEngine) -> None:
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            user_id, subscription_id, _old_plan_id = await _seed_user_plan_subscription(seed_session)
            plan_x = Plan(
                name="Plano X",
                slug=f"plano-x-{uuid.uuid4()}",
                price_cents=14990,
                billing_period=BillingPeriod.MENSAL,
                features={},
                is_active=True,
            )
            plan_y = Plan(
                name="Plano Y",
                slug=f"plano-y-{uuid.uuid4()}",
                price_cents=19990,
                billing_period=BillingPeriod.MENSAL,
                features={},
                is_active=True,
            )
            seed_session.add_all([plan_x, plan_y])
            await seed_session.commit()
            plan_x_id, plan_y_id = plan_x.id, plan_y.id

        async with factory() as s1, factory() as s2:
            service_a = SubscriptionService(s1)
            service_b = SubscriptionService(s2)
            results = await asyncio.gather(
                service_a.change_plan(subscription_id, user_id, plan_x_id),
                service_b.change_plan(subscription_id, user_id, plan_y_id),
                return_exceptions=True,
            )

        # `asyncio.gather` agenda as duas corrotinas cooperativamente, mas
        # NÃO garante que as duas cheguem ao banco genuinamente ao mesmo
        # tempo — dependendo do agendamento do event loop, dois desfechos
        # são igualmente válidos aqui (achado desta sessão, ver
        # IMPLEMENTATION_LOG.md): contenção real (uma perde o CAS, história
        # count == 1) ou A terminar por completo antes de B sequer ler (B
        # então lê o plano já trocado por A e aplica uma SEGUNDA troca
        # legítima e sequencial, plan_x -> plan_y — history_count == 2, e
        # não é duplicação, são duas transições reais). Nenhuma das duas
        # deve levantar erro (planos X e Y são diferentes, então mesmo no
        # caso sequencial o guard "já está neste plano" não dispara).
        for result in results:
            assert not isinstance(result, Exception), result

        async with factory() as check_session:
            history_count = await _history_count(check_session, subscription_id)
            assert history_count in (1, 2), history_count
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None

            if history_count == 1:
                # Contenção real: só uma das duas trocas foi aplicada, e o
                # plano final é exatamente um dos dois alvos.
                assert subscription.plan_id in (plan_x_id, plan_y_id)
            else:
                # Não-contenção: as duas trocas foram aplicadas em
                # sequência. O plano final tem que ser o alvo da SEGUNDA
                # transição gravada (ordem de `created_at`), e a cadeia de
                # `from_plan_id`/`to_plan_id` tem que ser contígua — sem
                # isso, seria uma corrida mal protegida de verdade, não
                # duas escritas sequenciais legítimas.
                stmt = (
                    select(SubscriptionHistory)
                    .where(SubscriptionHistory.subscription_id == subscription_id)
                    .order_by(SubscriptionHistory.created_at)
                )
                entries = (await check_session.execute(stmt)).scalars().all()
                assert len(entries) == 2
                first, second = entries
                assert first.to_plan_id == second.from_plan_id
                assert second.to_plan_id == subscription.plan_id
                assert {first.to_plan_id, second.to_plan_id} == {plan_x_id, plan_y_id}


class TestActivateSubscriptionConcurrencyReal:
    async def test_two_concurrent_activations_only_one_history_entry(
        self, db_engine: AsyncEngine
    ) -> None:
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            _user_id, subscription_id, _ = await _seed_user_plan_subscription(
                seed_session, status=SubscriptionStatus.PENDENTE
            )

        async with factory() as s1, factory() as s2:
            service_a = SubscriptionService(s1)
            service_b = SubscriptionService(s2)
            results = await asyncio.gather(
                service_a.activate_subscription(subscription_id),
                service_b.activate_subscription(subscription_id),
                return_exceptions=True,
            )

        for result in results:
            assert not isinstance(result, Exception), result

        async with factory() as check_session:
            assert await _history_count(check_session, subscription_id) == 1
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None
            assert subscription.status == SubscriptionStatus.ATIVA


class TestExpireSubscriptionConcurrencyReal:
    async def test_two_concurrent_expirations_only_one_history_entry(
        self, db_engine: AsyncEngine
    ) -> None:
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            _user_id, subscription_id, _ = await _seed_user_plan_subscription(seed_session)

        async with factory() as s1, factory() as s2:
            service_a = SubscriptionService(s1)
            service_b = SubscriptionService(s2)
            results = await asyncio.gather(
                service_a.expire_subscription(subscription_id),
                service_b.expire_subscription(subscription_id),
                return_exceptions=True,
            )

        for result in results:
            assert not isinstance(result, Exception), result

        async with factory() as check_session:
            assert await _history_count(check_session, subscription_id) == 1
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None
            assert subscription.status == SubscriptionStatus.EXPIRADA


class TestMarkPaymentFailedConcurrencyReal:
    async def test_two_concurrent_failures_only_one_history_entry(self, db_engine: AsyncEngine) -> None:
        factory = _session_factory(db_engine)
        async with factory() as seed_session:
            _user_id, subscription_id, _ = await _seed_user_plan_subscription(seed_session)

        async with factory() as s1, factory() as s2:
            service_a = SubscriptionService(s1)
            service_b = SubscriptionService(s2)
            results = await asyncio.gather(
                service_a.mark_payment_failed(subscription_id),
                service_b.mark_payment_failed(subscription_id),
                return_exceptions=True,
            )

        for result in results:
            assert not isinstance(result, Exception), result

        async with factory() as check_session:
            assert await _history_count(check_session, subscription_id) == 1
            subscription = await check_session.get(Subscription, subscription_id)
            assert subscription is not None
            assert subscription.status == SubscriptionStatus.INADIMPLENTE