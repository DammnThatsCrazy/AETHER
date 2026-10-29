"""Agent trust vs reputation (WO-094, ADR-AB-011).

Trust and reputation are kept apart and both live under Risk:

* **Trust** — Aether's own, evidence-qualified view of whether an agent can be
  relied on for a capability: competency, authority compliance, failure
  resolution. Computed from behavior facts; uncalibrated.
* **Reputation** — what other parties report about the agent (ratings,
  reviews, listings). Source-asserted; never blended into trust.

Neither is a fraud finding or an authorization decision.
"""
from __future__ import annotations

from typing import Any, Iterable


def trust_profile(model: dict[str, Any], authority_checks: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    checks = list(authority_checks)
    outside = sum(1 for chk in checks if chk.get("status") == "outside")
    known = sum(1 for chk in checks if chk.get("status") in {"inside", "outside"})
    per_capability = []
    for comp in model.get("competencies", []):
        env = comp["success"]
        per_capability.append({
            "capability": comp["capability"],
            "reliability": env["value"],
            "interval": env["interval"],
            "sufficiency": env["sufficiency"],
        })
    resolution = model["features"].get("failure_resolution_rate", {})
    return {
        "kind": "trust",
        "agent_ref": model["agent_ref"],
        "per_capability": per_capability,
        "authority_compliance": {
            "checked": known, "outside": outside,
            "rate": round(1 - outside / known, 4) if known else None,
        },
        "failure_recovery": resolution.get("value"),
        "calibration": "uncalibrated",
        "basis": "derived",
        "not": ["fraud finding", "authorization decision", "reputation"],
    }


def reputation_profile(agent_ref: str, reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    reports = list(reports)
    by_source: dict[str, list[float]] = {}
    for r in reports:
        if isinstance(r.get("rating"), (int, float)):
            by_source.setdefault(str(r.get("source") or "unknown"), []).append(float(r["rating"]))
    return {
        "kind": "reputation",
        "agent_ref": agent_ref,
        "sources": [{"source": s, "reports": len(v), "mean_rating": round(sum(v) / len(v), 4)}
                    for s, v in sorted(by_source.items())],
        "basis": "declared" if reports else "unknown",
        "note": "Third-party assertions; not combined with Aether trust.",
    }
