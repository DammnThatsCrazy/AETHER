"""Aether Shared — Feature Gate

Plan-based access control. Maps incoming request paths to a service in
SERVICE_CATALOG and checks whether the requesting plan has access. Public
paths (health, docs) and unrecognized paths pass through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared.auth.auth import PlanTier
from shared.plans.service_catalog import (
    MINIMUM_PLAN_FOR_SERVICE,
    resolve_service,
)
from shared.rate_limit.metrics import GATE_BLOCKED, GATE_TOTAL


PUBLIC_PATHS: frozenset[str] = frozenset({
    "/",
    "/health",
    "/v1/health",
    "/v1/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
    # Stripe webhook: protected by Stripe-Signature verification, not by
    # AETHER API keys. The route handler verifies the signature before
    # processing the payload.
    "/v1/admin/billing/stripe/webhook",
})


@dataclass
class GateResult:
    allowed: bool
    service_name: Optional[str]      # None if path didn't match a service
    access_tier: Optional[str]       # Plan-specific access label, if allowed
    minimum_plan: Optional[PlanTier] # Lowest plan with access, if blocked


class FeatureGate:
    """Stateless plan-vs-service gate. Safe for concurrent use."""

    def is_public(self, request_path: str) -> bool:
        return request_path in PUBLIC_PATHS

    def check_access(self, plan_tier: PlanTier, request_path: str) -> GateResult:
        if request_path in PUBLIC_PATHS:
            return GateResult(
                allowed=True,
                service_name=None,
                access_tier=None,
                minimum_plan=None,
            )

        service = resolve_service(request_path)
        if service is None:
            # Unrecognized path: not in registry. Let the route handler
            # decide (likely 404). Gate stays out of the way.
            return GateResult(
                allowed=True,
                service_name=None,
                access_tier=None,
                minimum_plan=None,
            )

        access_tier = service.plan_access.get(plan_tier)
        if access_tier is None:
            min_plan = MINIMUM_PLAN_FOR_SERVICE.get(service.name)
            try:
                GATE_TOTAL.labels(
                    tenant_id="*",
                    plan_tier=plan_tier.value,
                    service=service.name,
                    status="blocked",
                ).inc()
                GATE_BLOCKED.labels(
                    tenant_id="*",
                    plan_tier=plan_tier.value,
                    service=service.name,
                    required_plan=min_plan.value if min_plan else "P4",
                ).inc()
            except Exception:
                pass
            return GateResult(
                allowed=False,
                service_name=service.name,
                access_tier=None,
                minimum_plan=min_plan,
            )
        try:
            GATE_TOTAL.labels(
                tenant_id="*",
                plan_tier=plan_tier.value,
                service=service.name,
                status="allowed",
            ).inc()
        except Exception:
            pass
        return GateResult(
            allowed=True,
            service_name=service.name,
            access_tier=access_tier,
            minimum_plan=None,
        )
