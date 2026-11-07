"""W4 characterization: which existing limits cover Access Kit read routes.

These pin today's behavior so a later plan, per-credential, or spend limit is a
deliberate change. They do not assert that today's coverage is sufficient; see
docs/architecture/target/access-kit-w4-limits-contract.md.
"""
from __future__ import annotations

import pytest

from shared.auth.auth import PlanTier
from shared.plans.service_catalog import resolve_service
from shared.rate_limit.feature_gate import FeatureGate

_ACCESS_KIT_READ_PATHS = (
    "/v1/experience360/frames",
    "/v1/me",
    "/v1/entities",
    "/v1/capability-catalog",
    "/v1/billing/usage/summary",
)


@pytest.mark.parametrize("path", _ACCESS_KIT_READ_PATHS)
def test_access_kit_read_routes_are_not_plan_gated_services(path):
    # No catalog service owns these paths, so the plan gate passes every tier and
    # monthly overage cannot be attributed to a service. Adding a service entry is
    # a pricing decision for the billing owner.
    assert resolve_service(path) is None
    for tier in PlanTier:
        assert FeatureGate().check_access(tier, path).allowed is True


def test_agent_behavior_reads_stay_plan_gated():
    # The one Access Kit read family that is already a catalog service.
    service = resolve_service("/v1/agent/agents/agent-1/behavior")
    assert service is not None
    assert FeatureGate().check_access(PlanTier.ALPHA, "/v1/agent/agents/agent-1/behavior").allowed is False
