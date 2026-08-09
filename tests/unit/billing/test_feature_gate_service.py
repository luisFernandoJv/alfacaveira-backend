"""Testes unitários de `FeatureGateService`.

Cobre: resolução do plano efetivo (assinatura ativa vs. FREE por
convenção — ver docstring do service), `has_feature`/`assert_feature`,
limite de quota (`get_quota_limit`) e a checagem de quota já consumida
(`assert_within_quota`).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.enums import FeatureKey
from app.services.billing import feature_gate_service as feature_gate_service_module
from app.services.billing.feature_gate_service import FREE_PLAN_SLUG, FeatureGateService
from tests.unit.billing.factories import make_plan, make_subscription
from tests.unit.billing.fakes import (
    FakeAsyncSession,
    FakePlanRepository,
    FakeSubscriptionRepository,
)


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch):
    subs = FakeSubscriptionRepository()
    plans = FakePlanRepository()
    monkeypatch.setattr(feature_gate_service_module, "SubscriptionRepository", lambda session: subs)
    monkeypatch.setattr(feature_gate_service_module, "PlanRepository", lambda session: plans)
    return subs, plans


@pytest.fixture
def service(repos) -> FeatureGateService:
    return FeatureGateService(FakeAsyncSession())


class TestGetEffectivePlan:
    async def test_returns_plan_of_active_subscription(self, repos, service):
        subs, plans = repos
        plan = make_plan(slug="pro")
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        result = await service.get_effective_plan(user_id)

        assert result.slug == "pro"

    async def test_falls_back_to_free_plan_without_active_subscription(self, repos, service):
        subs, plans = repos
        free_plan = make_plan(slug=FREE_PLAN_SLUG)
        plans.seed(free_plan)

        result = await service.get_effective_plan(uuid.uuid4())

        assert result.slug == FREE_PLAN_SLUG

    async def test_raises_when_free_plan_is_not_seeded(self, repos, service):
        with pytest.raises(NotFoundError):
            await service.get_effective_plan(uuid.uuid4())


class TestHasFeatureAndAssertFeature:
    async def test_has_feature_true_when_plan_includes_it(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[(FeatureKey.SIMULADOS, None)])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        assert await service.has_feature(user_id, FeatureKey.SIMULADOS) is True

    async def test_has_feature_false_when_plan_does_not_include_it(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        assert await service.has_feature(user_id, FeatureKey.SIMULADOS) is False

    async def test_assert_feature_raises_forbidden_when_missing(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        with pytest.raises(ForbiddenError):
            await service.assert_feature(user_id, FeatureKey.SIMULADOS)

    async def test_assert_feature_passes_silently_when_present(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[(FeatureKey.SIMULADOS, None)])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        await service.assert_feature(user_id, FeatureKey.SIMULADOS)  # não deve levantar


class TestGetQuotaLimit:
    async def test_returns_none_for_unlimited_quota(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[(FeatureKey.DAILY_QUESTIONS, None)])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        assert await service.get_quota_limit(user_id, FeatureKey.DAILY_QUESTIONS) is None

    async def test_returns_configured_limit(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[(FeatureKey.DAILY_QUESTIONS, 5)])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        assert await service.get_quota_limit(user_id, FeatureKey.DAILY_QUESTIONS) == 5

    async def test_raises_forbidden_when_feature_not_granted(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        with pytest.raises(ForbiddenError):
            await service.get_quota_limit(user_id, FeatureKey.DAILY_QUESTIONS)


class TestAssertWithinQuota:
    async def test_passes_when_usage_below_limit(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[(FeatureKey.DAILY_QUESTIONS, 5)])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        await service.assert_within_quota(user_id, FeatureKey.DAILY_QUESTIONS, current_usage=4)

    async def test_raises_when_usage_reached_limit(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[(FeatureKey.DAILY_QUESTIONS, 5)])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        with pytest.raises(ForbiddenError):
            await service.assert_within_quota(user_id, FeatureKey.DAILY_QUESTIONS, current_usage=5)

    async def test_unlimited_quota_never_raises(self, repos, service):
        subs, plans = repos
        plan = make_plan(features=[(FeatureKey.DAILY_QUESTIONS, None)])
        user_id = uuid.uuid4()
        subs.seed(make_subscription(user_id=user_id, plan=plan))

        await service.assert_within_quota(user_id, FeatureKey.DAILY_QUESTIONS, current_usage=999999)