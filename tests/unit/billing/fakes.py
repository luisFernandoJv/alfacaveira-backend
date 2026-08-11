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
from datetime import datetime, timedelta
from typing import Any

from app.models.enums import SubscriptionStatus


class FakeAsyncSession:
    """Cobre o que os services chamam em self._session (.add, .flush, .commit, .rollback, .execute, .get)."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0
        self._store: dict[tuple[type, uuid.UUID], object] = {}

    def add(self, entity: object) -> None:
        self.added.append(entity)
        if hasattr(entity, "id") and entity.id is not None:
            key = (type(entity), entity.id)
            self._store[key] = entity

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def execute(self, stmt: object) -> object:
        from unittest.mock import MagicMock

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_result.unique = MagicMock(return_value=mock_result)
        mock_result.first = MagicMock(return_value=None)
        mock_result.all = MagicMock(return_value=[])
        return mock_result

    async def get(self, model: type, entity_id: uuid.UUID) -> object | None:
        key = (model, entity_id)
        return self._store.get(key)


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

    async def list_due_for_renewal(self, now: datetime):
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

    async def list_scheduled_cancellations_due(self, now: datetime):
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

    async def list_due_for_dunning_retry(self, now: datetime, *, max_attempts: int):
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

    async def list_due_for_dunning_expiration(self, now: datetime):
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

    async def list_due_for_renewal_reminder(self, now: datetime, days_before: int):
        target_date = now + timedelta(days=days_before)
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        return sorted(
            (
                s
                for s in self.store.values()
                if s.status == SubscriptionStatus.ATIVA
                and s.current_period_end >= start_of_day
                and s.current_period_end < end_of_day
                and not s.cancel_at_period_end
                and s.renewal_reminder_sent_at is None
            ),
            key=lambda s: s.current_period_end,
        )

    async def mark_renewal_reminder_sent(self, subscription_id: uuid.UUID, now: datetime) -> None:
        if subscription_id in self.store:
            self.store[subscription_id].renewal_reminder_sent_at = now

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
    monkeypatch (ADR-023)."""

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
        payment = self.store.get(payment_id)
        if payment is None or payment.status != expected_status:
            return False
        payment.status = new_status
        if paid_at is not None:
            payment.paid_at = paid_at
        return True


class FakeUserRepository:
    """Fake para UserRepository (PROMPT 13)."""

    def __init__(self, session: object = None) -> None:
        self.store: dict[uuid.UUID, object] = {}

    def seed(self, *users: object) -> None:
        for u in users:
            if hasattr(u, "id"):
                self.store[u.id] = u

    async def get_by_id(self, user_id: uuid.UUID):
        return self.store.get(user_id)

    async def get_by_email(self, email: str):
        for u in self.store.values():
            if hasattr(u, "email") and u.email == email:
                return u
        return None


class FakeSubscriptionNotificationService:
    """Fake para SubscriptionNotificationService (PROMPT 13)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _add_call(self, event: str, user, subscription, **kwargs) -> None:
        self.calls.append({
            "event": event,
            "user": user,
            "subscription": subscription,
            **kwargs,
        })

    async def notify_payment_approved(self, user, subscription):
        self._add_call("payment_approved", user, subscription)

    async def notify_payment_failed(self, user, subscription):
        self._add_call("payment_failed", user, subscription)

    async def notify_renewal_success(self, user, subscription):
        self._add_call("renewal_success", user, subscription)

    async def notify_renewal_reminder(self, user, subscription):
        self._add_call("renewal_reminder", user, subscription)

    async def notify_cancellation(self, user, subscription):
        self._add_call("cancellation", user, subscription)

    async def notify_reactivation(self, user, subscription):
        self._add_call("reactivation", user, subscription)

    async def notify_plan_change(self, user, subscription, old_plan_name: str):
        self._add_call("plan_change", user, subscription, old_plan_name=old_plan_name)

    async def notify_dunning_recovered(self, user, subscription):
        self._add_call("dunning_recovered", user, subscription)

    async def notify_dunning_retry_failed(self, user, subscription):
        self._add_call("dunning_retry_failed", user, subscription)

    async def notify_dunning_expired(self, user, subscription):
        self._add_call("dunning_expired", user, subscription)

    def clear(self) -> None:
        self.calls = []

    def assert_called_with(self, event: str, **kwargs) -> None:
        for call in self.calls:
            if call["event"] == event:
                for key, value in kwargs.items():
                    if call.get(key) != value:
                        break
                else:
                    return
        raise AssertionError(f"Chamada com evento '{event}' não encontrada em {self.calls}")