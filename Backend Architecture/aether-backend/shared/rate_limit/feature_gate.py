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
    "/ready",
    "/v1/ready",
    "/v1/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
    # Stripe webhook: protected by Stripe-Signature verification, not by
    # Aether API keys. The route handler verifies the signature before
    # processing the payload.
    "/v1/admin/billing/stripe/webhook",
    # Public registration: unauthenticated tenant sign-up endpoint.
    "/v1/tenants",
    # Public recovery: unauthenticated key recovery (never returns a key in body).
    "/v1/auth/recover",
    # Email+password sign-up flow (public — tenant created only after OTP verification).
    "/v1/auth/register",
    "/v1/auth/verify-email",
    "/v1/auth/resend-verification",
    # Public plan catalog used during signup and upgrade discovery.
    "/v1/billing/plans",
    # Email+password login (returns session API key).
    "/v1/auth/login",
    # Loopback-restricted and mounted only by local/dev backend profiles.
    "/v1/auth/development-session",
    # SSO via Auth0 (Google, Apple, Microsoft, Twitter/X, Slack).
    "/v1/auth/sso/callback",
    "/v1/auth/sso/providers",
    # One-time, staging-only first-admin bootstrap. The handler requires a
    # high-entropy Secrets Manager token and an allowlisted operator email.
    "/v1/auth/bootstrap/first-admin",
})

# Path prefixes that bypass Aether API key auth.
# Each entry is a prefix string — any path starting with it is public.
# These routes MUST authenticate themselves (e.g. HMAC signature verification).
PUBLIC_PATH_PREFIXES: frozenset[str] = frozenset({
    # Verified source-link redirect: reached unauthenticated from bios/QR/emails.
    # The handler validates the signed token, records the use, and mints a
    # one-time handoff before redirecting to the link's own stored destination.
    "/v1/r/",
    # Provider webhooks: unauthenticated by API key; HMAC-verified inside the handler.
    "/v1/integrations/webhooks/",
    # UPR provider webhook gateway: unauthenticated by API key; verified via the
    # provider plugin's webhook signature verification inside the handler.
    "/v1/provider-webhooks/",
    # Notification-service-mounted inbound provider callbacks (Linear, Jira, generic webhook).
    # Each route verifies its own HMAC signature before processing.
    "/v1/notifications/webhooks/linear/",
    "/v1/notifications/webhooks/jira/",
    "/v1/notifications/webhooks/aether/",
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
