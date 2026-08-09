"""Testes unitários dos schemas Pydantic de `app/schemas/billing/`.

Cobre: validação/serialização de request e response, `from_attributes`
(construção a partir dos models ORM), defaults e rejeição de payload
inválido (`slug` fora do padrão, `price_cents` negativo, `plan_id`
ausente/mal formado).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.models.enums import (
    BillingPeriod,
    FeatureKey,
    FeatureKind,
    PaymentStatus,
    SubscriptionStatus,
)
from app.schemas.billing.payment import PaymentResponse, PaymentWebhookEventRequest
from app.schemas.billing.plan import (
    FeatureCreateRequest,
    PlanCreateRequest,
    PlanResponse,
    PlanUpdateRequest,
    SetPlanFeatureRequest,
)
from app.schemas.billing.subscription import (
    CancelSubscriptionRequest,
    ChangePlanRequest,
    CreateSubscriptionRequest,
    SubscriptionResponse,
)
from tests.unit.billing.factories import make_payment, make_plan, make_subscription


class TestPlanCreateRequest:
    def test_accepts_valid_payload(self):
        req = PlanCreateRequest(
            name="Standard", slug="standard", price_cents=4990, billing_period=BillingPeriod.MENSAL
        )
        assert req.is_active is True  # default

    def test_rejects_slug_with_invalid_characters(self):
        with pytest.raises(ValidationError):
            PlanCreateRequest(
                name="Standard",
                slug="Standard Plan!",
                price_cents=4990,
                billing_period=BillingPeriod.MENSAL,
            )

    def test_rejects_negative_price(self):
        with pytest.raises(ValidationError):
            PlanCreateRequest(
                name="Standard",
                slug="standard",
                price_cents=-1,
                billing_period=BillingPeriod.MENSAL,
            )


class TestPlanUpdateRequest:
    def test_all_fields_are_optional(self):
        req = PlanUpdateRequest()
        assert req.name is None
        assert req.price_cents is None
        assert req.billing_period is None
        assert req.is_active is None

    def test_partial_update_keeps_unspecified_fields_none(self):
        req = PlanUpdateRequest(price_cents=1000)
        assert req.price_cents == 1000
        assert req.name is None


class TestSetPlanFeatureRequest:
    def test_accepts_null_quota_limit(self):
        req = SetPlanFeatureRequest(feature_key=FeatureKey.SIMULADOS, quota_limit=None)
        assert req.quota_limit is None

    def test_rejects_negative_quota_limit(self):
        with pytest.raises(ValidationError):
            SetPlanFeatureRequest(feature_key=FeatureKey.SIMULADOS, quota_limit=-1)


class TestFeatureCreateRequest:
    def test_accepts_valid_payload(self):
        req = FeatureCreateRequest(
            key=FeatureKey.SIMULADOS, kind=FeatureKind.BOOLEAN, name="Simulados"
        )
        assert req.is_active is True

    def test_rejects_name_too_short(self):
        with pytest.raises(ValidationError):
            FeatureCreateRequest(key=FeatureKey.SIMULADOS, kind=FeatureKind.BOOLEAN, name="A")


class TestPlanResponseFromAttributes:
    def test_builds_from_orm_model_with_plan_features(self):
        plan = make_plan(
            slug="pro", features=[(FeatureKey.SIMULADOS, None), (FeatureKey.DAILY_QUESTIONS, 5)]
        )

        response = PlanResponse.model_validate(plan)

        assert response.slug == "pro"
        assert len(response.plan_features) == 2
        keys = {pf.feature.key for pf in response.plan_features}
        assert keys == {FeatureKey.SIMULADOS, FeatureKey.DAILY_QUESTIONS}


class TestSubscriptionResponseFromAttributes:
    def test_builds_from_orm_model(self):
        plan = make_plan(slug="pro")
        sub = make_subscription(plan=plan, status=SubscriptionStatus.ATIVA)

        response = SubscriptionResponse.model_validate(sub)

        assert response.status == SubscriptionStatus.ATIVA
        assert response.plan.slug == "pro"
        assert response.cancel_at_period_end is False


class TestCreateSubscriptionRequest:
    def test_requires_plan_id(self):
        with pytest.raises(ValidationError):
            CreateSubscriptionRequest()

    def test_accepts_valid_uuid(self):
        plan_id = uuid.uuid4()
        req = CreateSubscriptionRequest(plan_id=plan_id)
        assert req.plan_id == plan_id

    def test_rejects_malformed_uuid(self):
        with pytest.raises(ValidationError):
            CreateSubscriptionRequest(plan_id="not-a-uuid")


class TestChangePlanRequest:
    def test_requires_new_plan_id(self):
        with pytest.raises(ValidationError):
            ChangePlanRequest()


class TestCancelSubscriptionRequest:
    def test_defaults_to_scheduled_cancellation(self):
        req = CancelSubscriptionRequest()
        assert req.immediately is False

    def test_accepts_immediate_flag(self):
        req = CancelSubscriptionRequest(immediately=True)
        assert req.immediately is True


class TestPaymentResponseFromAttributes:
    def test_builds_from_orm_model(self):
        payment = make_payment(subscription_id=uuid.uuid4(), status=PaymentStatus.APROVADO)

        response = PaymentResponse.model_validate(payment)

        assert response.status == PaymentStatus.APROVADO
        assert response.currency == "BRL"


class TestPaymentWebhookEventRequest:
    def test_accepts_valid_payload(self):
        req = PaymentWebhookEventRequest(
            provider_payment_id="pay_123", status=PaymentStatus.APROVADO
        )
        assert req.status == PaymentStatus.APROVADO

    def test_rejects_invalid_status_value(self):
        with pytest.raises(ValidationError):
            PaymentWebhookEventRequest(provider_payment_id="pay_123", status="not-a-status")

    def test_requires_provider_payment_id(self):
        with pytest.raises(ValidationError):
            PaymentWebhookEventRequest(status=PaymentStatus.APROVADO)