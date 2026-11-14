"""Segment lenses: Campaign 360, Geographic 360, Communications 360, Journey 360.

Each discovered pattern carries a ``segment_profile``: the share of the
affected entities' events in each cohort dimension value (campaign, channel,
geography, application, entity kind, agent type), computed by the engine
from the run's evidence, and ``segment_keys`` (``dimension=value`` with at
least :data:`SEGMENT_KEY_SHARE` of the events), indexed for lookup.

A lens shows the surfaced patterns that concentrate in its subject:

* ``campaign360`` / ``<campaign id>``     — ``campaign=<id>``
* ``geographic360`` / ``<country code>``  — ``geography=<CC>``
* ``communication360`` / ``<channel>``    — ``channel=<channel>`` (email, sms, push, ...);
  ``all`` lists every pattern with a channel dimension or a communication reading
* ``journey360`` / ``<profile id>``       — entity-scoped, the journey-shaped
  subset (sequences, failure → recovery, bursts, lockstep, segment shifts,
  baseline changes) of the patterns involving that profile; consent-gated

Lenses are read-only views over the same records as every other surface.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .contracts import (
    KIND_LOCKSTEP, KIND_OUTLIER, KIND_SEGMENT_SHIFT, KIND_SEQUENCE, KIND_TEMPORAL_BURST, VISIBLE_STATUSES,
)

SEGMENT_KEY_SHARE = 0.2
#: lens -> (cohort dimension, normalise subject)
SEGMENT_LENSES: dict[str, tuple[str, Any]] = {
    "campaign360": ("campaign", lambda v: v.strip()),
    "geographic360": ("geography", lambda v: v.strip().upper()),
    "communication360": ("channel", lambda v: v.strip().lower()),
}
ENTITY_LENSES = ("journey360",)
LENSES = tuple(SEGMENT_LENSES) + ENTITY_LENSES
_JOURNEY_KINDS = (KIND_SEQUENCE, KIND_TEMPORAL_BURST, KIND_LOCKSTEP, KIND_SEGMENT_SHIFT, KIND_OUTLIER)
_KIND_HEADINGS = {
    "sequence": "Recurring sequences",
    "shared_attribute_cluster": "Shared infrastructure and identifiers",
    "behavioral_cohort": "Look-alike cohorts",
    "temporal_burst": "Unusual timing",
    "lockstep": "Coordinated activity",
    "behavioral_outlier": "Extreme behaviour",
    "novel_motif": "New graph structures",
    "schema_drift": "Source changes",
    "segment_shift": "Localized shifts",
    "agent_spawn_anomaly": "Agent spawning",
    "agent_tool_signature": "Shared agent playbooks",
    "agent_interaction_cluster": "Agent-to-agent activity",
    "traffic_anomaly": "Traffic anomalies",
    "cross_domain": "Linked signals",
}


def segment_profile(events, dims_limit: int = 3) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """``({dim: [{value, share}]}, ["dim=value", ...])`` for a set of events."""
    counts: dict[str, Counter] = {}
    for e in events:
        for dim, val in (e.segments or {}).items():
            counts.setdefault(dim, Counter())[val] += 1
    profile: dict[str, list[dict[str, Any]]] = {}
    keys: list[str] = []
    for dim, c in sorted(counts.items()):
        total = sum(c.values()) or 1
        top = [{"value": v, "share": round(n / total, 3)} for v, n in c.most_common(dims_limit)]
        profile[dim] = top
        keys += [f"{dim}={t['value']}" for t in top if t["share"] >= SEGMENT_KEY_SHARE]
    return profile, sorted(set(keys))


def lens_segment_key(lens: str, subject: str) -> str:
    dim, norm = SEGMENT_LENSES[lens]
    return f"{dim}={norm(subject)}"


def _row(p: dict[str, Any]) -> dict[str, Any]:
    out = {k: p.get(k) for k in (
        "pattern_id", "kind", "summary", "status", "severity", "confidence", "novelty",
        "affected_entity_count", "risk_categories", "first_observed_at", "last_observed_at",
        "pinned", "surfaced_at", "changed_at", "segment_keys",
    )}
    out["title"] = p.get("display_title") or p.get("title")
    return out


def lens_view(lens: str, subject: str, patterns: list[dict[str, Any]]) -> dict[str, Any]:
    visible = [p for p in patterns if p.get("status") in VISIBLE_STATUSES]
    if lens == "journey360":
        visible = [p for p in visible if p.get("kind") in _JOURNEY_KINDS
                   or any(e.get("type") == "failure_then_success" for e in p.get("evidence") or [])]
    visible.sort(key=lambda p: (not p.get("pinned"), -float(p.get("severity_score") or 0), p.get("pattern_id", "")))
    groups: dict[str, list[dict[str, Any]]] = {}
    for p in visible:
        groups.setdefault(p.get("kind"), []).append(_row(p))
    return {
        "lens": lens,
        "subject": subject,
        "advisory": True,
        "claim_state": "inferred",
        "counts": {"total": len(visible), "by_kind": {k: len(v) for k, v in groups.items()}},
        "groups": [{"kind": k, "heading": _KIND_HEADINGS.get(k, k), "patterns": rows}
                   for k, rows in groups.items()],
        "patterns": [_row(p) for p in visible],
    }
