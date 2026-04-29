"""Aether Plans — Service Catalog

Canonical registry of all 34 Aether services. Translates the Rate Limiting
tab into code: per-service pricing across the 3 pricing options and the
plan-gating matrix.

Plan access values:
  - None        : service blocked for that plan (HTTP 403)
  - any string  : access tier label (e.g. "Included", "Advanced", "Core Feature")
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from shared.auth.auth import PlanTier
from shared.plans.models import ServiceDefinition, ServicePricing


_P1 = PlanTier.P1_HOBBYIST
_P2 = PlanTier.P2_PROFESSIONAL
_P3 = PlanTier.P3_GROWTH_INTELLIGENCE
_P4 = PlanTier.P4_PROTOCOL_MASTER


def _pricing(cost: str, opt_a: str, opt_b: str, opt_c: str) -> ServicePricing:
    return ServicePricing(
        cost_per_1k=Decimal(cost),
        option_a_per_1k=Decimal(opt_a),
        option_b_per_1k=Decimal(opt_b),
        option_c_per_1k=Decimal(opt_c),
    )


# 34-service registry. Numeric values match the Rate Limiting tab exactly.
SERVICE_CATALOG: list[ServiceDefinition] = [
    # 1. Omni-Capture (Ingestion)
    ServiceDefinition(
        name="Omni-Capture",
        pillar="Ingestion",
        endpoint_pattern="/v1/ingest/*",
        pricing=_pricing("0.02", "0.05", "0.08", "0.12"),
        plan_access={_P1: "Included", _P2: "Included", _P3: "Included", _P4: "Included"},
    ),
    # 2. Truth-Store (Data Lake)
    ServiceDefinition(
        name="Truth-Store",
        pillar="Data Lake",
        endpoint_pattern="/v1/lake/*",
        pricing=_pricing("0.65", "1.63", "2.60", "3.50"),
        plan_access={_P1: "Included", _P2: "Included", _P3: "Included", _P4: "Included"},
    ),
    # 3. Efficiency (Ingestion)
    ServiceDefinition(
        name="Efficiency",
        pillar="Ingestion",
        endpoint_pattern="/v1/batch",
        pricing=_pricing("0.01", "0.03", "0.04", "0.06"),
        plan_access={_P1: "Included", _P2: "Included", _P3: "Included", _P4: "Included"},
    ),
    # 4. Compliance (Consent)
    ServiceDefinition(
        name="Compliance",
        pillar="Consent",
        endpoint_pattern="/v1/consent/*",
        pricing=_pricing("0.04", "0.10", "0.16", "0.25"),
        plan_access={_P1: "Included", _P2: "Included", _P3: "Included", _P4: "Included"},
    ),
    # 5. Protocol-Map (Web3)
    ServiceDefinition(
        name="Protocol-Map",
        pillar="Web3",
        endpoint_pattern="/v1/web3/*",
        pricing=_pricing("0.40", "1.00", "1.60", "2.50"),
        plan_access={_P1: "Included", _P2: "Included", _P3: "Included", _P4: "Included"},
    ),
    # 6. Health-Check (Diagnostics)
    ServiceDefinition(
        name="Health-Check",
        pillar="Diagnostics",
        endpoint_pattern="/v1/diagnostics/*",
        pricing=_pricing("0.02", "0.05", "0.08", "0.12"),
        plan_access={_P1: "Included", _P2: "Included", _P3: "Included", _P4: "Included"},
    ),
    # 7. Governance (Admin)
    ServiceDefinition(
        name="Governance",
        pillar="Admin",
        endpoint_pattern="/v1/admin/*",
        pricing=_pricing("0.01", "0.03", "0.04", "0.06"),
        plan_access={_P1: "Single-Tenant", _P2: "Multi-App", _P3: "Enterprise", _P4: "Sovereign"},
    ),
    # 8. Traffic-Ctrl (Routing)
    ServiceDefinition(
        name="Traffic-Ctrl",
        pillar="Routing",
        endpoint_pattern="/v1/gateway",
        pricing=_pricing("0.01", "0.03", "0.04", "0.06"),
        plan_access={_P1: "Included", _P2: "Included", _P3: "Included", _P4: "Included"},
    ),
    # 9. Reporting (Intelligence)
    ServiceDefinition(
        name="Reporting",
        pillar="Intelligence",
        endpoint_pattern="/v1/analytics",
        pricing=_pricing("0.08", "0.20", "0.32", "0.50"),
        plan_access={_P1: "Standard", _P2: "Advanced", _P3: "Custom", _P4: "Global"},
    ),
    # 10. Source-ID (Enrichment)
    ServiceDefinition(
        name="Source-ID",
        pillar="Enrichment",
        endpoint_pattern="/v1/traffic",
        pricing=_pricing("0.04", "0.10", "0.16", "0.25"),
        plan_access={_P1: "Basic", _P2: "Advanced", _P3: "Deep-Trace", _P4: "Global"},
    ),
    # 11. Unification (Identity)
    ServiceDefinition(
        name="Unification",
        pillar="Identity",
        endpoint_pattern="/v1/identity/*",
        pricing=_pricing("0.25", "0.63", "1.00", "1.50"),
        plan_access={_P1: None, _P2: "Core Feature", _P3: "Advanced", _P4: "Cross-Domain"},
    ),
    # 12. Ledger-Sync (On-Chain)
    ServiceDefinition(
        name="Ledger-Sync",
        pillar="On-Chain",
        endpoint_pattern="/v1/onchain/*",
        pricing=_pricing("0.35", "0.88", "1.40", "2.00"),
        plan_access={_P1: None, _P2: "Core Feature", _P3: "Advanced", _P4: "Cross-Domain"},
    ),
    # 13. Profile-360 (Profile)
    ServiceDefinition(
        name="Profile-360",
        pillar="Profile",
        endpoint_pattern="/v1/profile/*",
        pricing=_pricing("0.03", "0.08", "0.12", "0.20"),
        plan_access={_P1: None, _P2: "Core Feature", _P3: "Advanced", _P4: "Dedicated"},
    ),
    # 14. Orchestration (Providers)
    ServiceDefinition(
        name="Orchestration",
        pillar="Providers",
        endpoint_pattern="/v1/providers/*",
        pricing=_pricing("0.05", "0.13", "0.20", "0.30"),
        plan_access={_P1: None, _P2: "Core Feature", _P3: "Expanded", _P4: "Custom BYOK"},
    ),
    # 15. Pipeline-Ops (Automation)
    ServiceDefinition(
        name="Pipeline-Ops",
        pillar="Automation",
        endpoint_pattern="/v1/automation/*",
        pricing=_pricing("0.07", "0.18", "0.28", "0.45"),
        plan_access={_P1: None, _P2: "Standard", _P3: "High-Freq", _P4: "Custom"},
    ),
    # 16. Access-Control (Entitlements)
    ServiceDefinition(
        name="Access-Control",
        pillar="Entitlements",
        endpoint_pattern="/v1/entitlements/*",
        pricing=_pricing("0.10", "0.25", "0.40", "0.60"),
        plan_access={_P1: None, _P2: "Standard", _P3: "High-Freq", _P4: "Custom"},
    ),
    # 17. Alerting (Messaging)
    ServiceDefinition(
        name="Alerting",
        pillar="Messaging",
        endpoint_pattern="/v1/notification/*",
        pricing=_pricing("0.07", "0.18", "0.28", "0.45"),
        plan_access={_P1: None, _P2: "Basic", _P3: "Behavioral", _P4: "Real-Time"},
    ),
    # 18. Redaction (Security)
    ServiceDefinition(
        name="Redaction",
        pillar="Security",
        endpoint_pattern="/v1/privacy/*",
        pricing=_pricing("0.10", "0.25", "0.40", "0.60"),
        plan_access={_P1: None, _P2: "Standard", _P3: "PII-Shield", _P4: "Custom"},
    ),
    # 19. Campaign-Mgmt (Marketing)
    ServiceDefinition(
        name="Campaign-Mgmt",
        pillar="Marketing",
        endpoint_pattern="/v1/campaign",
        pricing=_pricing("0.05", "0.13", "0.20", "0.30"),
        plan_access={_P1: None, _P2: "Included", _P3: "Multi-Touch", _P4: "Predictive"},
    ),
    # 20. Autonomy (Agentic)
    ServiceDefinition(
        name="Autonomy",
        pillar="Agentic",
        endpoint_pattern="/v1/agent/*",
        pricing=_pricing("1.80", "4.50", "7.20", "10.80"),
        plan_access={_P1: None, _P2: None, _P3: "Core Feature", _P4: "Core Feature"},
    ),
    # 21. Insights (Intelligence)
    ServiceDefinition(
        name="Insights",
        pillar="Intelligence",
        endpoint_pattern="/v1/intelligence/*",
        pricing=_pricing("0.15", "0.38", "0.60", "0.90"),
        plan_access={_P1: None, _P2: None, _P3: "Core Feature", _P4: "Sovereign"},
    ),
    # 22. Prediction (ML Inference)
    ServiceDefinition(
        name="Prediction",
        pillar="ML Inference",
        endpoint_pattern="/v1/ml/*",
        pricing=_pricing("0.05", "0.13", "0.20", "0.30"),
        plan_access={_P1: None, _P2: None, _P3: "Core Feature", _P4: "Custom Models"},
    ),
    # 23. Connectivity (Graph)
    ServiceDefinition(
        name="Connectivity",
        pillar="Graph",
        endpoint_pattern="/v1/graph",
        pricing=_pricing("0.12", "0.31", "0.50", "0.75"),
        plan_access={_P1: None, _P2: None, _P3: "Core Feature", _P4: "Core Feature"},
    ),
    # 24. Retail-Intel (Commerce)
    ServiceDefinition(
        name="Retail-Intel",
        pillar="Commerce",
        endpoint_pattern="/v1/commerce/*",
        pricing=_pricing("0.50", "1.25", "2.00", "3.00"),
        plan_access={_P1: None, _P2: None, _P3: "Core Feature", _P4: "Core Feature"},
    ),
    # 25. Defense (Fraud)
    ServiceDefinition(
        name="Defense",
        pillar="Fraud",
        endpoint_pattern="/v1/fraud/*",
        pricing=_pricing("0.22", "0.55", "0.88", "1.25"),
        plan_access={_P1: None, _P2: None, _P3: "Core Feature", _P4: "Adversarial"},
    ),
    # 26. ROI-Proof (Attribution)
    ServiceDefinition(
        name="ROI-Proof",
        pillar="Attribution",
        endpoint_pattern="/v1/attribution/*",
        pricing=_pricing("0.45", "1.13", "1.80", "2.75"),
        plan_access={_P1: None, _P2: None, _P3: "Included", _P4: "Redistribution"},
    ),
    # 27. Friction-Sense (Behavioral)
    ServiceDefinition(
        name="Friction-Sense",
        pillar="Behavioral",
        endpoint_pattern="/v1/behavioral/*",
        pricing=_pricing("0.55", "1.38", "2.20", "3.30"),
        plan_access={_P1: None, _P2: None, _P3: "Included", _P4: "Predictive"},
    ),
    # 28. Negative-Space (Expectations)
    ServiceDefinition(
        name="Negative-Space",
        pillar="Expectations",
        endpoint_pattern="/v1/expectations/*",
        pricing=_pricing("0.42", "1.05", "1.70", "2.50"),
        plan_access={_P1: None, _P2: None, _P3: "Included", _P4: "Predictive"},
    ),
    # 29. Cohort-IQ (Population)
    ServiceDefinition(
        name="Cohort-IQ",
        pillar="Population",
        endpoint_pattern="/v1/population/*",
        pricing=_pricing("0.38", "0.94", "1.50", "2.25"),
        plan_access={_P1: None, _P2: None, _P3: "Included", _P4: "Global"},
    ),
    # 30. Verification (Oracle)
    ServiceDefinition(
        name="Verification",
        pillar="Oracle",
        endpoint_pattern="/v1/oracle/*",
        pricing=_pricing("0.18", "0.45", "0.72", "1.10"),
        plan_access={_P1: None, _P2: None, _P3: None, _P4: "Core Feature"},
    ),
    # 31. Settlement (Commerce)
    ServiceDefinition(
        name="Settlement",
        pillar="Commerce",
        endpoint_pattern="/v1/x402/*",
        pricing=_pricing("0.08", "0.20", "0.32", "0.50"),
        plan_access={_P1: None, _P2: None, _P3: None, _P4: "Core Feature"},
    ),
    # 32. Incentives (Rewards)
    ServiceDefinition(
        name="Incentives",
        pillar="Rewards",
        endpoint_pattern="/v1/rewards/*",
        pricing=_pricing("0.30", "0.75", "1.20", "1.80"),
        plan_access={_P1: None, _P2: None, _P3: None, _P4: "Core Feature"},
    ),
    # 33. Asset-Bridge (RWA)
    ServiceDefinition(
        name="Asset-Bridge",
        pillar="RWA",
        endpoint_pattern="/v1/rwa/*",
        pricing=_pricing("0.90", "2.25", "3.60", "5.00"),
        plan_access={_P1: None, _P2: None, _P3: None, _P4: "Core Feature"},
    ),
    # 34. Fusion (Cross-Domain)
    ServiceDefinition(
        name="Fusion",
        pillar="Cross-Domain",
        endpoint_pattern="/v1/crossdomain/*",
        pricing=_pricing("0.06", "0.15", "0.24", "0.40"),
        plan_access={_P1: None, _P2: None, _P3: None, _P4: "Core Feature"},
    ),
]


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert an endpoint pattern like '/v1/ingest/*' to a regex.

    Wildcard '*' matches anything (including additional path segments).
    A pattern without wildcards matches the path exactly OR with a trailing
    sub-path so that, e.g., '/v1/gateway' matches '/v1/gateway/foo'.
    """
    if "*" in pattern:
        escaped = re.escape(pattern).replace(r"\*", ".*")
        return re.compile(f"^{escaped}$")
    # Exact match or sub-path under it.
    escaped = re.escape(pattern)
    return re.compile(f"^{escaped}(/.*)?$")


# Pre-compiled (regex, ServiceDefinition) tuples for endpoint resolution.
ENDPOINT_MATCHERS: list[tuple[re.Pattern, ServiceDefinition]] = [
    (_pattern_to_regex(svc.endpoint_pattern), svc) for svc in SERVICE_CATALOG
]


# Pre-compute the minimum (lowest) PlanTier that grants access to each service.
_PLAN_ORDER = (_P1, _P2, _P3, _P4)
MINIMUM_PLAN_FOR_SERVICE: dict[str, PlanTier] = {}
for _svc in SERVICE_CATALOG:
    for _tier in _PLAN_ORDER:
        if _svc.plan_access.get(_tier) is not None:
            MINIMUM_PLAN_FOR_SERVICE[_svc.name] = _tier
            break


def resolve_service(path: str) -> Optional[ServiceDefinition]:
    """Return the ServiceDefinition that matches a request path, or None."""
    for pattern, svc in ENDPOINT_MATCHERS:
        if pattern.match(path):
            return svc
    return None


def check_plan_access(plan_tier: PlanTier, service: ServiceDefinition) -> Optional[str]:
    """Return the access tier label if the plan can use the service, else None."""
    return service.plan_access.get(plan_tier)


def find_service_by_name(name: str) -> Optional[ServiceDefinition]:
    """Linear lookup by service name. Used by overage billing."""
    for svc in SERVICE_CATALOG:
        if svc.name == name:
            return svc
    return None
