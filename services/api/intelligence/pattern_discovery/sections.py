"""Profile 360, Agent 360 and Risk 360 sections built from discovered patterns.

Each section is a read over the patterns implicating one entity, shaped for
the 360 surface that renders it. All three are advisory (``claim_state:
inferred`` unless a reviewer confirmed the pattern, in which case the row
carries its reviewed status), and all three are released only with an
affirmative analytics consent receipt for the entity (enforced by the service).

* **Profile 360** — emerging patterns, similar profiles and behavioural
  cohorts, unresolved identity overlaps, contradictory evidence (patterns about
  the profile that reviewers judged differently), and changes from the
  profile's own baseline (outlier / segment-shift / burst patterns).
* **Agent 360** — novel delegation motifs, tool-call signatures, sub-agent
  spawning anomalies, shared infrastructure with other agents, behaviour
  repeated across unrelated principals, and agent-to-agent interaction.
* **Risk 360** — pattern-based findings with severity, novelty, confidence and
  evidence coverage, cross-profile campaigns, emerging clusters, graph motifs,
  temporal anomalies, review status, and the Risk360 signals promotion wrote.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .contracts import (
    KIND_AGENT_INTERACTION, KIND_AGENT_SPAWN, KIND_AGENT_TOOL_SIGNATURE, KIND_BEHAVIORAL_COHORT,
    KIND_CROSS_DOMAIN, KIND_LOCKSTEP, KIND_NOVEL_MOTIF, KIND_OUTLIER, KIND_SEGMENT_SHIFT,
    KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE, KIND_TEMPORAL_BURST, KIND_TRAFFIC_ANOMALY,
    QUEUE_STATUSES, REVIEWED_STATUSES, STATUS_PROMOTED,
)

_DELEGATION_EDGES = ("DELEGATED_BY", "SPAWNED_BY")


def _row(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p.get(k) for k in (
        "pattern_id", "kind", "title", "summary", "status", "priority", "severity", "confidence",
        "confidence_cap", "novelty", "affected_entity_count", "risk_categories", "first_observed_at",
        "last_observed_at", "version", "times_observed", "claim_state",
    )}


def _live(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in patterns if p.get("status") not in ("deprecated", "duplicate")]


def _of(patterns, *kinds):
    return [_row(p) for p in patterns if p.get("kind") in kinds]


def _co_implicated(entity_key: str, patterns, kinds=None, prefix=None, limit=10):
    co = Counter()
    for p in patterns:
        if kinds and p.get("kind") not in kinds:
            continue
        for other in p.get("affected_entity_keys") or []:
            if other != entity_key and (prefix is None or other.startswith(prefix)):
                co[other] += 1
    return [{"entity": e, "shared_patterns": c} for e, c in co.most_common(limit)]


def _base(entity_key: str, surface: str, patterns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "entity": entity_key,
        "surface": surface,
        "advisory": True,
        "claim_state": "inferred",
        "note": "Discovered patterns are review material; they never merge identities or change decisions.",
        "counts": {
            "total": len(patterns),
            "open": sum(1 for p in patterns if p.get("status") in QUEUE_STATUSES or p.get("status") == "candidate"),
            "reviewed": sum(1 for p in patterns if p.get("status") in REVIEWED_STATUSES),
            "promoted": sum(1 for p in patterns if p.get("status") == STATUS_PROMOTED),
        },
    }


def profile_section(entity_key: str, patterns: list[dict[str, Any]]) -> dict[str, Any]:
    live = _live(patterns)
    verdicts: dict[str, set[str]] = {}
    for p in live:
        if p.get("status") in REVIEWED_STATUSES or p.get("status") == STATUS_PROMOTED:
            verdicts.setdefault(p.get("family") or p.get("kind"), set()).add(p.get("status"))
    contradictory = [
        _row(p) for p in live
        if len({s for s in verdicts.get(p.get("family") or p.get("kind"), set())}
               & {"benign", "confirmed_malicious", "confirmed_valid", "promoted"}) >= 2
    ]
    return {
        **_base(entity_key, "profile360", live),
        "emerging_patterns": [_row(p) for p in live if p.get("status") in QUEUE_STATUSES or p.get("status") == "candidate"],
        "similar_profiles": _co_implicated(entity_key, live, prefix=None),
        "behavioral_cohorts": _of(live, KIND_BEHAVIORAL_COHORT, KIND_LOCKSTEP, KIND_SEQUENCE),
        "unresolved_identity_overlaps": [
            _row(p) for p in live
            if any(e.get("type") == "identity_overlap_candidate" for e in p.get("evidence") or [])
        ],
        "contradictory_evidence": contradictory,
        "baseline_changes": _of(live, KIND_OUTLIER, KIND_SEGMENT_SHIFT, KIND_TEMPORAL_BURST),
    }


def agent_section(entity_key: str, patterns: list[dict[str, Any]]) -> dict[str, Any]:
    live = _live(patterns)
    delegation_motifs = [
        _row(p) for p in live if p.get("kind") == KIND_NOVEL_MOTIF
        and any(any(edge in str(lbl) for edge in _DELEGATION_EDGES) for lbl in (p.get("signature") or {}).get("edges", []))
    ]
    return {
        **_base(entity_key, "agent360", live),
        "novel_delegation_motifs": delegation_motifs,
        "tool_call_signatures": _of(live, KIND_AGENT_TOOL_SIGNATURE),
        "spawning_anomalies": _of(live, KIND_AGENT_SPAWN),
        "shared_infrastructure": _of(live, KIND_SHARED_ATTRIBUTE),
        "shared_infrastructure_agents": _co_implicated(entity_key, live, kinds={KIND_SHARED_ATTRIBUTE}, prefix="agent:"),
        "cross_principal_behavior": _of(live, KIND_AGENT_TOOL_SIGNATURE, KIND_BEHAVIORAL_COHORT, KIND_LOCKSTEP),
        "agent_interactions": _of(live, KIND_AGENT_INTERACTION),
        "principals": _co_implicated(entity_key, live, kinds={KIND_AGENT_TOOL_SIGNATURE, KIND_AGENT_INTERACTION},
                                     prefix="user:"),
    }


def risk_section(entity_key: str, patterns: list[dict[str, Any]]) -> dict[str, Any]:
    live = _live(patterns)
    findings = []
    for p in sorted(live, key=lambda p: (-float(p.get("severity_score") or 0), p.get("pattern_id", ""))):
        evidence = p.get("evidence") or []
        findings.append({
            **_row(p),
            "severity_score": p.get("severity_score"),
            "evidence_coverage": {
                "items": len(evidence),
                "observed": sum(1 for e in evidence if e.get("basis") == "observed"),
                "inferred": sum(1 for e in evidence if e.get("basis") == "inferred"),
                "event_refs": sum(len(e.get("source_event_refs") or []) for e in evidence),
            },
            "review_status": p.get("status"),
            "risk_signals": [o for o in ((p.get("promotion") or {}).get("risk_signals") or [])
                             if o.get("entity") == entity_key and o.get("status") == "written"],
        })
    cats = Counter(c for p in live for c in p.get("risk_categories") or [])
    return {
        **_base(entity_key, "risk360", live),
        "pattern_findings": findings,
        "campaigns": _of(live, KIND_CROSS_DOMAIN),
        "emerging_clusters": _of(live, KIND_SHARED_ATTRIBUTE, KIND_BEHAVIORAL_COHORT, KIND_AGENT_INTERACTION),
        "graph_motifs": _of(live, KIND_NOVEL_MOTIF),
        "temporal_anomalies": _of(live, KIND_TEMPORAL_BURST, KIND_LOCKSTEP, KIND_TRAFFIC_ANOMALY, KIND_SEGMENT_SHIFT),
        "risk_category_counts": dict(cats.most_common()),
        "max_novelty": max((float(p.get("novelty") or 0) for p in live), default=0.0),
        "max_confidence": max((float(p.get("confidence") or 0) for p in live), default=0.0),
    }


SECTIONS = {"profile360": profile_section, "agent360": agent_section, "risk360": risk_section}
