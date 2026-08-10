"""Dublês (fakes) reutilizados pelos testes unitários de billing.

Não dependem de banco real nem de uma `AsyncSession` de verdade — cada
`Fake*Repository` guarda os registros num dict em memória e implementa
apenas os métodos que os services de fato chamam. Mesmo espírito de
`tests/unit/test_rate_limit_middleware.py` (PROMPT 03): isolado, sem
depender de infra externa (ver docs/HANDOFF.md, pendência 6 —
`tests/conftest.py` ainda é só um placeholder).
"""

from __future__ import annotations

import uuid

from app.models.enums import SubscriptionStatus


class FakeAsyncSession:
    """Cobre só o que os services chamam diretamente em `self._session`
    (`.add`, `.flush`) e o que `UnitOfWork` chama ao sair do bloco
    (`.commit`, `.rollback`)."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0

    def add(self, entity: object) -> None:
        self.added.append(entity)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeSubscriptionRepository:
    """Substitui `app.repositories.billing.subscription_repository.
    SubscriptionRepository` nos módulos de service via monkeypatch."""

    def __init__(self, session: object = None) -> None:
        self.store: dict[uuid.UUID, object] = {}

    def seed(self, *subscriptions: object) -> None:
        for s in subscriptions:
            self.store[s.id] = s

    async def get_active_by_user(self, user_id: uuid.UUID):
        for s in self.store.values():
            if s.user_id == user_id and s.status == SubscriptionStatus.ATIVA:
                return s
        return None

    async def get_pending_by_user(self, user_id: uuid.UUID):
        """Espelha `SubscriptionRepository.get_pending_by_user` real
        (PROMPT 05 / ADR-014) — usado por `create_subscription` para
        rejeitar uma segunda assinatura PENDENTE do mesmo usuário."""
        for s in self.store.values():
            if s.user_id == user_id and s.status == SubscriptionStatus.PENDENTE:
                return s
        return None

    async def get_by_id_with_plan(self, subscription_id: uuid.UUID):
        return self.store.get(subscription_id)

    async def get_owned(self, subscription_id: uuid.UUID, user_id: uuid.UUID):
        s = self.store.get(subscription_id)
        if s is not None and s.user_id == user_id:
            return s
        return None

    async def list_by_user(self, user_id: uuid.UUID):
        return [s for s in self.store.values() if s.user_id == user_id]

    async def get_by_id(self, subscription_id: uuid.UUID):
        return self.store.get(subscription_id)

    async def list_due_for_renewal(self, now):
        """Espelha `SubscriptionRepository.list_due_for_renewal` real
        (PROMPT 10) — usado pelo job de renovação automática."""
        return sorted(
            (
                s
                for s in self.store.values()
                if s.status == SubscriptionStatus.ATIVA
                and not s.cancel_at_period_end
                and s.current_period_end <= now
            ),
            key=lambda s: s.current_period_end,
        )

    async def list_scheduled_cancellations_due(self, now):
        """Espelha `SubscriptionRepository.list_scheduled_cancellations_due`
        real (PROMPT 10) — usado pelo job de renovação automática para
        efetivar cancelamentos agendados vencidos."""
        return sorted(
            (
                s
                for s in self.store.values()
                if s.status == SubscriptionStatus.ATIVA
                and s.cancel_at_period_end
                and s.current_period_end <= now
            ),
            key=lambda s: s.current_period_end,
        )

    async def list_due_for_dunning_retry(self, now, *, max_attempts: int):
        """Espelha `SubscriptionRepository.list_due_for_dunning_retry` real
        (PROMPT 11) — usado pelo job de dunning."""
        return sorted(
            (
                s
                for s in self.store.values()
                if s.status == SubscriptionStatus.INADIMPLENTE
                and s.dunning_attempts < max_attempts
                and s.dunning_next_retry_at is not None
                and s.dunning_next_retry_at <= now
            ),
            key=lambda s: s.dunning_next_retry_at,
        )

    async def list_due_for_dunning_expiration(self, now):
        """Espelha `SubscriptionRepository.list_due_for_dunning_expiration`
        real (PROMPT 11) — usado pelo job de dunning para expirar
        assinaturas cujo grace period terminou."""
        return sorted(
            (
                s
                for s in self.store.values()
                if s.status == SubscriptionStatus.INADIMPLENTE
                and s.dunning_grace_period_ends_at is not None
                and s.dunning_grace_period_ends_at <= now
            ),
            key=lambda s: s.dunning_grace_period_ends_at,
        )

    async def add(self, entity: object):
        self.store[entity.id] = entity
        return entity

    async def compare_and_swap(
        self,
        subscription_id: uuid.UUID,
        *,
        expected: dict[str, object],
        values: dict[str, object],
    ) -> bool:
        """Espelha `SubscriptionRepository.compare_and_swap` real
        (ADR-019). Não há `await` entre a checagem e a escrita — mesmo
        raciocínio de atomicidade do ponto de vista do loop de eventos já
        documentado em `compare_and_swap_status` abaixo, agora
        generalizado para qualquer coluna em `expected`/`values`, não só
        `status`.
        """
        sub = self.store.get(subscription_id)
        if sub is None:
            return False
        for column_name, expected_value in expected.items():
            if getattr(sub, column_name) != expected_value:
                return False
        for column_name, new_value in values.items():
            setattr(sub, column_name, new_value)
        return True

    async def compare_and_swap_status(
        self,
        subscription_id: uuid.UUID,
        *,
        expected_status,
        new_status,
        period_start=None,
        period_end=None,
    ) -> bool:
        """Espelha `SubscriptionRepository.compare_and_swap_status` real
        (roadmap item 7, ADR-017/ADR-018) — desde o ADR-019, atalho fino
        sobre `compare_and_swap` acima, mesmo espírito do real. Reproduz a
        corrida e a correção de forma determinística em `asyncio.gather`
        sem precisar de banco real (mesma técnica do `asyncio.sleep(0)` já
        usada em `TestMarkPaymentFailedConcurrencyFinding`, mas aplicada
        do lado que decide se a escrita acontece, não do lado da leitura).

        `period_start`/`period_end` opcionais espelham o mesmo par no
        repositório real (ADR-018, usado por `activate_subscription`).
        """
        values: dict[str, object] = {"status": new_status}
        if period_start is not None:
            values["current_period_start"] = period_start
        if period_end is not None:
            values["current_period_end"] = period_end
        return await self.compare_and_swap(
            subscription_id,
            expected={"status": expected_status},
            values=values,
        )


class FakeSubscriptionHistoryRepository:
    """Substitui `SubscriptionHistoryRepository` nos módulos de service via
    monkeypatch (ADR-023). Não guarda estado próprio — lê diretamente de
    `session.added` (a mesma `FakeAsyncSession` usada pelo service), porque
    `SubscriptionService` grava entradas de histórico via
    `self._session.add(SubscriptionHistory(...))`, não via este
    repositório. Isto mantém as duas visões (o que foi adicionado à sessão
    e o que este repositório "vê" ao consultar) sempre em sincronia entre
    chamadas sucessivas dentro do mesmo teste, sem duplicar armazenamento.
    """

    def __init__(self, session: object) -> None:
        self._session = session

    async def get_by_subscription_and_payment(
        self, subscription_id: uuid.UUID, payment_id: uuid.UUID
    ):
        for entry in getattr(self._session, "added", []):
            if (
                getattr(entry, "subscription_id", None) == subscription_id
                and getattr(entry, "payment_id", None) == payment_id
            ):
                return entry
        return None

    async def get_latest(self, subscription_id: uuid.UUID):
        candidates = [
            e
            for e in getattr(self._session, "added", [])
            if getattr(e, "subscription_id", None) == subscription_id and hasattr(e, "reason")
        ]
        if not candidates:
            return None
        # `session.added` preserva ordem de inserção — a última é a mais
        # recente (mesmo espírito de `ORDER BY created_at DESC LIMIT 1` do
        # repositório real).
        return candidates[-1]


class FakePlanRepository:
    """Substitui `PlanRepository` nos módulos de service via monkeypatch."""

    def __init__(self, session: object = None) -> None:
        self.store: dict[uuid.UUID, object] = {}

    def seed(self, *plans: object) -> None:
        for p in plans:
            self.store[p.id] = p

    async def get_by_id(self, plan_id: uuid.UUID):
        return self.store.get(plan_id)

    async def get_by_slug(self, slug: str):
        return next((p for p in self.store.values() if p.slug == slug), None)

    async def get_by_slug_with_features(self, slug: str):
        return next((p for p in self.store.values() if p.slug == slug), None)

    async def get_with_features(self, plan_id: uuid.UUID):
        return self.store.get(plan_id)

    async def list_active(self):
        return [p for p in self.store.values() if p.is_active]


class FakePaymentRepository:
    """Substitui `PaymentRepository` em `payment_service` via monkeypatch."""

    def __init__(self, session: object = None) -> None:
        self.store: dict[uuid.UUID, object] = {}

    def seed(self, *payments: object) -> None:
        for p in payments:
            self.store[p.id] = p

    async def get_by_provider_payment_id(self, provider_payment_id: str):
        return next(
            (p for p in self.store.values() if p.provider_payment_id == provider_payment_id),
            None,
        )

    async def list_by_subscription(self, subscription_id: uuid.UUID):
        return [p for p in self.store.values() if p.subscription_id == subscription_id]

    async def add(self, entity: object):
        self.store[entity.id] = entity
        return entity

    async def compare_and_swap_status(
        self, payment_id: uuid.UUID, *, expected_status, new_status, paid_at=None
    ) -> bool:
        """Espelha `PaymentRepository.compare_and_swap_status` real
        (roadmap item 7, ADR-017) — ver o comentário equivalente em
        `FakeSubscriptionRepository.compare_and_swap_status` sobre por
        que isto é seguro sem banco real."""
        payment = self.store.get(payment_id)
        if payment is None or payment.status != expected_status:
            return False
        payment.status = new_status
        if paid_at is not None:
            payment.paid_at = paid_at
        return True