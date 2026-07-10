"""Release readiness checks for Cluster Targeting Intelligence."""

from __future__ import annotations

from typing import Any

from config.settings import settings


async def release_readiness() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def _check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # Contracts importable and non-execution invariants enforced.
    try:
        from services.targeting_intelligence.models import TargetingIntent
        try:
            TargetingIntent(tenantId="t", source="tenant_declared",
                            executionByAether=True)  # type: ignore[arg-type]
            _check("non_execution_invariant", False,
                   "executionByAether=True was accepted")
        except Exception:
            _check("non_execution_invariant", True)
        _check("contracts_importable", True)
    except Exception as exc:  # pragma: no cover — import failure is the finding
        _check("contracts_importable", False, str(exc))

    # Policy engine deterministic on a fixture.
    try:
        from services.targeting_intelligence.models import ClusterTargetingRule
        from services.targeting_intelligence.policy import ClusterSignals, resolve_cluster
        rules = [
            ClusterTargetingRule(clusterId="c1", ruleType="include"),
            ClusterTargetingRule(clusterId="c1", ruleType="exclude"),
        ]
        first = resolve_cluster("t", "c1", rules, ClusterSignals(consent_blocked=True))
        second = resolve_cluster("t", "c1", rules, ClusterSignals(consent_blocked=True))
        _check(
            "policy_deterministic_consent_wins",
            first.resolution == second.resolution == "hard_consent_block",
        )
    except Exception as exc:
        _check("policy_deterministic_consent_wins", False, str(exc))

    # Stores reachable.
    try:
        from services.targeting_intelligence.repository import get_targeting_repositories
        repos = get_targeting_repositories()
        await repos.intents.list_for_tenant("__readiness__", limit=1)
        _check("stores_reachable", True)
    except Exception as exc:
        _check("stores_reachable", False, str(exc))

    flags = settings.targeting_intelligence
    _check("flags_present", hasattr(flags, "enabled") and hasattr(flags, "exports_enabled"))

    return {
        "ready": all(c["passed"] for c in checks),
        "checks": checks,
        "flags": {
            "enabled": flags.enabled,
            "exports_enabled": flags.exports_enabled,
            "ooda_suggestions_enabled": flags.ooda_suggestions_enabled,
            "kyber_enabled": flags.kyber_enabled,
        },
    }
