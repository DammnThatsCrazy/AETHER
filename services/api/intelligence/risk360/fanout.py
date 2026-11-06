"""Principal fan-out analysis over the lineage projection (AO-9).

Risk owns classification; the lineage projection only supplies neutral counts.
Three rules shape everything here:

  * Scale is context. Agent count, spawn velocity, depth and tool volume are
    reported, and on their own they can never move a principal above ``benign``.
  * Attribution kinds never collapse. An agent in a risky cluster is not a risky
    agent, and resembling risky behaviour is not confirmed malice.
  * Propagation is recorded by kind (exposure, association, influence, verified
    action, inferred relationship) and never turns into a finding about someone
    downstream. Only a verified action is carried as an observed fact.

A signal the evidence cannot support is ``None``, never ``0``.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Iterable, Optional

from graph.operational_intelligence.models import EvidenceRef
from shared.agent_lineage import vocabulary as V
from shared.contracts_models.epistemic import EpistemicStatus

from .contracts import RiskSignal
from .signals import _evidence_id, _signal_id

SOURCE = "agent_lineage_fanout"
DETECTOR_VERSION = "agent_lineage_fanout/1"

#: Reported on every assessment. Thresholds have never been fit to adjudicated
#: outcomes, so nothing here may be read as a calibrated probability.
POLICY = {
    "version": DETECTOR_VERSION, "calibrated": False, "elevated_rate": 0.05, "min_population": 5,
}
#: Evidence of misbehaviour, as opposed to mere size. Only these drive a segment.
BEHAVIORAL_SIGNALS = frozenset({
    "authority_failure_rate", "revoked_agent_activity", "out_of_scope_execution_rate",
})
#: Rates at or above this are elevated. Deliberately uncalibrated and reported as
#: heuristic: the score is ``None`` and the claim state ``DERIVED``.
ELEVATED_RATE = POLICY["elevated_rate"]
MIN_POPULATION = POLICY["min_population"]


def _rate(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 6)


def temporal_profile(activity: dict[str, Any]) -> dict[str, Any]:
    """Spawn acceleration against the principal's own history."""
    timeline = activity.get("spawn_timeline") or []
    if not timeline:
        return {
            "baseline_agent_count": None, "current_agent_count": None, "spawn_rate": None,
            "historical_percentile": None, "burst_at": None, "acceleration": None,
            "timeline_truncated": bool(activity.get("spawn_timeline_truncated")),
        }
    counts = [count for _, count in timeline]
    current_at, current = timeline[-1]
    peak_at, peak = max(timeline, key=lambda item: (item[1], -item[0]))
    earlier = counts[:-1]
    baseline = median(earlier) if earlier else None
    percentile = (
        round(sum(1 for value in earlier if value <= current) / len(earlier), 4) if earlier else None
    )
    bucket = activity.get("bucket_seconds") or 60.0
    return {
        "baseline_agent_count": baseline,
        "current_agent_count": current,
        "spawn_rate": round(peak / bucket, 4),
        "historical_percentile": percentile,
        "burst_at": peak_at,
        "acceleration": round(peak / baseline, 4) if baseline else None,
        "timeline_truncated": bool(activity.get("spawn_timeline_truncated")),
    }


def _identity_churn(summary: dict[str, Any], agents: Optional[int]) -> Optional[float]:
    definitions = summary.get("unique_agent_definitions")
    if definitions is None or not agents:
        return None
    return round(max(0.0, 1 - definitions / agents), 6)


def fanout_signals(summary: dict[str, Any]) -> dict[str, Optional[float]]:
    """The work order's fan-out vocabulary. Unsupported signals stay ``None``."""
    activity = summary.get("activity") or {}
    agents = activity.get("agent_count")
    events = activity.get("event_count")
    wallets = activity.get("wallet_count")
    providers = activity.get("provider_count")
    tools = activity.get("tool_count")
    transactions = activity.get("transaction_count")
    instance_total = activity.get("instance_total")
    temporal = temporal_profile(activity)
    signals: dict[str, Optional[float]] = {
        "agent_spawn_velocity": temporal["spawn_rate"],
        "delegation_fanout": activity.get("max_direct_fanout"),
        "delegation_depth": summary.get("max_delegation_depth"),
        "ephemeral_agent_ratio": _rate(activity.get("ephemeral_agents"), agents),
        "new_agent_rate": temporal["current_agent_count"],
        "cross_wallet_fanout": wallets or None,
        "tool_fanout": tools or None,
        "provider_fanout": providers or None,
        "transaction_fanout": transactions or None,
        "runtime_churn": _rate(instance_total, agents) if instance_total else None,
        # Agent ids beyond the logical identities they report. Context, never a trigger.
        "identity_churn": _identity_churn(summary, agents),
        "authority_failure_rate": _rate(activity.get("denied_event_count"), events),
        "revoked_agent_activity": activity.get("revoked_agent_activity"),
        "out_of_scope_execution_rate": _rate(summary.get("out_of_scope_agents"), agents),
        "shared_infrastructure_density": _rate(activity.get("shared_infra_largest_share"), agents),
        # Largest same-window, same-tools group. An uncalibrated share, context only.
        "coordinated_execution_score": _rate(activity.get("largest_coordinated_group"), agents),
    }
    return {name: signals[name] for name in V.FANOUT_RISK_SIGNALS}


def assess_principal(
    summary: dict[str, Any],
    *,
    clusters: Iterable[dict[str, Any]] = (),
    confirmed_malicious_agents: Optional[int] = None,
) -> dict[str, Any]:
    """Segment one principal's population. Scale alone never elevates anything."""
    activity = summary.get("activity") or {}
    if confirmed_malicious_agents is None:
        confirmed_malicious_agents = activity.get("confirmed_malicious_agents")
    agents = activity.get("agent_count")
    signals = fanout_signals(summary)
    triggered = _triggered(signals, agents)
    clusters = list(clusters)
    unresolved = summary.get("unresolved_agents")
    probabilistic = summary.get("probabilistic_agents")
    risk_flagged = summary.get("risk_flagged_agents")
    verified_effects = activity.get("verified_effect_count")
    # Elevated counts only what the evidence directly names, never the whole fleet.
    violators = (summary.get("out_of_scope_agents") or 0) + (summary.get("revoked_agents") or 0)
    elevated = None
    if agents is not None:
        elevated = min(agents, violators) if triggered else 0
    if agents is None:
        benign = None
    else:
        # ``agents`` counts linked agents only; unresolved ones are their own segment.
        benign = max(0, agents - (elevated or 0) - (confirmed_malicious_agents or 0))
    level = "unknown" if agents is None else ("elevated" if triggered else "no_behavioral_indicators")
    if confirmed_malicious_agents:
        level = "confirmed_activity"
    return {
        "tenant_id": summary.get("tenant_id"),
        "principal_entity_id": summary.get("principal_entity_id"),
        "assessment_level": level,
        "scale_is_context": True,
        "policy": dict(POLICY),
        "segments": {
            "attributable_agents": agents,
            "no_indicators": benign,
            "unresolved": _sum_known(unresolved, probabilistic),
            "elevated_risk": elevated,
            "confirmed_abusive": confirmed_malicious_agents,
        },
        "attribution_kinds": _attribution_kinds(summary, clusters, triggered, confirmed_malicious_agents),
        "signals": signals,
        "triggered_signals": sorted(triggered),
        "context_signals": sorted(name for name, value in signals.items()
                                  if value is not None and name not in BEHAVIORAL_SIGNALS),
        "temporal": temporal_profile(activity),
        "propagation": _propagation(summary),
        "attribution": {
            "verified_links": summary.get("verified_links"),
            "inferred_links": summary.get("inferred_links"),
            "probabilistic_links": probabilistic,
            "unresolved_links": unresolved,
            "note": "Verified and inferred links are separate claims; a suspected cluster proves no common control.",
        },
        "verified_external_effects": verified_effects,
        "disclosure": summary.get("disclosure"),
    }


def _sum_known(*values: Optional[int]) -> Optional[int]:
    return None if any(value is None for value in values) else sum(values)  # type: ignore[arg-type]


def _triggered(signals: dict[str, Optional[float]], agents: Optional[int]) -> set[str]:
    if not agents or agents < MIN_POPULATION:
        return set()
    triggered = set()
    for name in ("authority_failure_rate", "out_of_scope_execution_rate"):
        value = signals.get(name)
        if value is not None and value >= ELEVATED_RATE:
            triggered.add(name)
    if signals.get("revoked_agent_activity"):
        triggered.add("revoked_agent_activity")
    return triggered


def _attribution_kinds(
    summary: dict[str, Any], clusters: list[dict[str, Any]], triggered: set[str],
    confirmed: Optional[int],
) -> dict[str, Optional[int]]:
    """Each kind of risk relationship counted on its own; none implies another."""
    activity = summary.get("activity") or {}
    flagged_cluster_members = sum(
        cluster.get("member_count") or 0 for cluster in clusters if cluster.get("risk_flagged_count")
    ) if clusters else None
    return {
        "agent_is_risky": summary.get("risk_flagged_agents"),
        "agent_in_risky_cluster": flagged_cluster_members,
        "delegated_by_risky_actor": activity.get("delegated_by_risky_actor"),
        "interacted_with_risky_resource": activity.get("interacted_with_risky_resource"),
        "resembles_risky_behavior": activity.get("resembles_risky_behavior"),
        "confirmed_malicious": confirmed,
    }


def _propagation(summary: dict[str, Any]) -> list[dict[str, Any]]:
    activity = summary.get("activity") or {}
    return [
        {"kind": "verified_action", "subject": "external_effect", "count": activity.get("verified_effect_count"),
         "statement": "Effects with attested or reconciled evidence."},
        {"kind": "exposure", "subject": "wallet", "count": activity.get("wallet_count"),
         "statement": "Wallets touched by this population; touching a wallet implicates no owner."},
        {"kind": "association", "subject": "tool", "count": activity.get("tool_count"),
         "statement": "Tools used by this population; shared tool use is not coordination."},
        {"kind": "influence", "subject": "child_agent", "count": summary.get("indirect_agents"),
         "statement": "Agents delegated below the direct links."},
        {"kind": "inferred_relationship", "subject": "agent", "count": summary.get("inferred_links"),
         "statement": "Links resting on non-proof evidence."},
    ]


def _refs(summary: dict[str, Any], kind: str) -> list[EvidenceRef]:
    principal = summary.get("principal_entity_id")
    return [EvidenceRef(
        id=_evidence_id("agent_lineage", principal=principal, signal=kind),
        type="annotation",
        source=f"principal_agent_lineage_summary:{principal}",
    )]


def signals_from_assessment(
    summary: dict[str, Any], assessment: dict[str, Any], *, subject_kind: str = "entity",
) -> list[RiskSignal]:
    """Canonical Risk360 signals. Only behavioural triggers produce one; size never does."""
    tenant = summary["tenant_id"]
    principal = summary["principal_entity_id"]
    out = []
    for name in assessment["triggered_signals"]:
        claim = (
            EpistemicStatus.OBSERVED if name == "revoked_agent_activity" else EpistemicStatus.DERIVED
        )
        value = assessment["signals"].get(name)
        out.append(RiskSignal(
            signal_id=_signal_id(producer=SOURCE, tenant=tenant, principal=principal, kind=name),
            tenant_id=tenant, subject_kind=subject_kind, subject_id=principal, risk_dimension="agentic",
            claim_state=claim, confidence=None, evidence_refs=_refs(summary, name),
            source=f"{SOURCE}.{name}", detector_version=DETECTOR_VERSION, score=None,
            value=float(value) if value is not None else None,
        ))
    confirmed = assessment["segments"].get("confirmed_abusive")
    if confirmed:
        name = "confirmed_malicious_agents"
        out.append(RiskSignal(
            signal_id=_signal_id(producer=SOURCE, tenant=tenant, principal=principal, kind=name),
            tenant_id=tenant, subject_kind=subject_kind, subject_id=principal, risk_dimension="agentic",
            claim_state=EpistemicStatus.VERIFIED, confidence=None, evidence_refs=_refs(summary, name),
            source=f"{SOURCE}.{name}", detector_version=DETECTOR_VERSION, score=None, value=float(confirmed),
        ))
    return out
