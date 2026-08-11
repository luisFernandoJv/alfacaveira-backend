"""Helpers para instanciar models de billing em memória (sem sessão real),
usados pelos testes unitários de `SubscriptionService`, `PaymentService` e
`FeatureGateService`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.models.billing.feature import Feature
from app.models.billing.plan import Plan
from app.models.billing.plan_feature import PlanFeature
from app.models.billing.subscription import Subscription
from app.models.enums import BillingPeriod, FeatureKind, PaymentStatus, SubscriptionStatus
from app.models.identity.user import User


def make_feature(key, kind: FeatureKind = FeatureKind.BOOLEAN, is_active: bool = True) -> Feature:
    return Feature(id=uuid.uuid4(), key=key, kind=kind, name=key.value, is_active=is_active)


def make_user(
    *,
    email: str | None = None,
    full_name: str = "Usuário Teste",
    is_active: bool = True,
    is_admin: bool = False,
) -> User:
    """Cria um usuário de teste."""
    return User(
        id=uuid.uuid4(),
        email=email or f"teste-{uuid.uuid4()}@teste.com",
        full_name=full_name,
        is_active=is_active,
        is_admin=is_admin,
        password_hash="hash-nao-usado-em-testes",
    )


def make_plan(
    *,
    slug: str = "standard",
    name: str | None = None,
    price_cents: int = 4990,
    billing_period: BillingPeriod = BillingPeriod.MENSAL,
    is_active: bool = True,
    features: list[tuple] = (),
) -> Plan:
    """`features` é uma lista de tuplas `(FeatureKey, quota_limit | None)`.

    Se `name` não for fornecido, usa `slug.capitalize()` como nome.
    """
    plan_name = name or slug.capitalize()
    plan = Plan(
        id=uuid.uuid4(),
        name=plan_name,
        slug=slug,
        price_cents=price_cents,
        billing_period=billing_period,
        features={},
        is_active=is_active,
    )
    plan.plan_features = []
    plan.created_at = datetime.now(UTC)
    for key, quota_limit in features:
        feature = make_feature(key)
        pf = PlanFeature(
            id=uuid.uuid4(), plan_id=plan.id, feature_id=feature.id, quota_limit=quota_limit
        )
        pf.feature = feature
        pf.plan = plan
    return plan


def make_subscription(
    *,
    user_id: uuid.UUID | None = None,
    plan: Plan | None = None,
    status: SubscriptionStatus = SubscriptionStatus.ATIVA,
    cancel_at_period_end: bool = False,
    period_days: int = 30,
    dunning_attempts: int = 0,
    dunning_next_retry_at: datetime | None = None,
    dunning_grace_period_ends_at: datetime | None = None,
    renewal_reminder_sent_at: datetime | None = None,
) -> Subscription:
    plan = plan or make_plan()
    now = datetime.now(UTC)
    sub = Subscription(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        plan_id=plan.id,
        status=status,
        current_period_start=now,
        current_period_end=now + timedelta(days=period_days),
        cancel_at_period_end=cancel_at_period_end,
        dunning_attempts=dunning_attempts,
        dunning_next_retry_at=dunning_next_retry_at,
        dunning_grace_period_ends_at=dunning_grace_period_ends_at,
        renewal_reminder_sent_at=renewal_reminder_sent_at,
    )
    sub.plan = plan
    sub.history = []
    sub.payments = []
    sub.created_at = now
    return sub


def make_payment(
    *,
    subscription_id: uuid.UUID,
    status: PaymentStatus = PaymentStatus.PENDENTE,
    provider_payment_id: str | None = None,
    amount_cents: int = 4990,
):
    from app.models.billing.payment import Payment

    payment = Payment(
        id=uuid.uuid4(),
        subscription_id=subscription_id,
        amount_cents=amount_cents,
        currency="BRL",
        status=status,
        provider="console",
        provider_payment_id=provider_payment_id or str(uuid.uuid4()),
        paid_at=None,
    )
    payment.created_at = datetime.now(UTC)
    return payment