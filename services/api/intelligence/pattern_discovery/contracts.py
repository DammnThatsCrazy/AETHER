"""Pattern discovery vocabulary: kinds, lifecycle states, verdicts and records.

Records are plain JSON-able dicts on the wire and in storage (mirroring the
fleet-hypothesis store), built by the helpers here so every producer emits the
same shape. API request bodies are strict pydantic models (``extra="forbid"``).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DETECTOR_VERSION = "pattern_discovery/1.0.0"

# ── Pattern kinds ────────────────────────────────────────────────────────────
KIND_SEQUENCE = "sequence"
KIND_SHARED_ATTRIBUTE = "shared_attribute_cluster"
KIND_BEHAVIORAL_COHORT = "behavioral_cohort"
KIND_TEMPORAL_BURST = "temporal_burst"
KIND_LOCKSTEP = "lockstep"
KIND_OUTLIER = "behavioral_outlier"
KIND_NOVEL_MOTIF = "novel_motif"
KIND_SCHEMA_DRIFT = "schema_drift"
KIND_CROSS_DOMAIN = "cross_domain"
KIND_SEGMENT_SHIFT = "segment_shift"
KIND_AGENT_SPAWN = "agent_spawn_anomaly"
KIND_AGENT_TOOL_SIGNATURE = "agent_tool_signature"
KIND_AGENT_INTERACTION = "agent_interaction_cluster"
KIND_TRAFFIC_ANOMALY = "traffic_anomaly"

PATTERN_KINDS: tuple[str, ...] = (
    KIND_SEQUENCE,
    KIND_SHARED_ATTRIBUTE,
    KIND_BEHAVIORAL_COHORT,
    KIND_TEMPORAL_BURST,
    KIND_LOCKSTEP,
    KIND_OUTLIER,
    KIND_NOVEL_MOTIF,
    KIND_SCHEMA_DRIFT,
    KIND_SEGMENT_SHIFT,
    KIND_AGENT_SPAWN,
    KIND_AGENT_TOOL_SIGNATURE,
    KIND_AGENT_INTERACTION,
    KIND_TRAFFIC_ANOMALY,
    KIND_CROSS_DOMAIN,
)

#: Confidence ceiling per kind. Every detector here is statistical inference over
#: circumstantial evidence; only the cross-domain composite (independent
#: detectors agreeing on the same entities) and schema drift (a structural fact
#: about the payloads themselves) are allowed higher.
CONFIDENCE_CAPS: dict[str, float] = {
    KIND_SEQUENCE: 0.75,
    KIND_SHARED_ATTRIBUTE: 0.75,
    KIND_BEHAVIORAL_COHORT: 0.7,
    KIND_TEMPORAL_BURST: 0.7,
    KIND_LOCKSTEP: 0.75,
    KIND_OUTLIER: 0.65,
    KIND_NOVEL_MOTIF: 0.7,
    KIND_SCHEMA_DRIFT: 0.9,
    KIND_SEGMENT_SHIFT: 0.7,
    KIND_AGENT_SPAWN: 0.7,
    KIND_AGENT_TOOL_SIGNATURE: 0.75,
    KIND_AGENT_INTERACTION: 0.75,
    KIND_TRAFFIC_ANOMALY: 0.6,
    KIND_CROSS_DOMAIN: 0.85,
}

# ── Lifecycle ────────────────────────────────────────────────────────────────
STATUS_CANDIDATE = "candidate"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_CONFIRMED_VALID = "confirmed_valid"
STATUS_CONFIRMED_MALICIOUS = "confirmed_malicious"
STATUS_BENIGN = "benign"
STATUS_DUPLICATE = "duplicate"
STATUS_UNRESOLVED = "unresolved"
STATUS_PROMOTED = "promoted"
STATUS_DEPRECATED = "deprecated"

PATTERN_STATUSES: tuple[str, ...] = (
    STATUS_CANDIDATE,
    STATUS_NEEDS_REVIEW,
    STATUS_CONFIRMED_VALID,
    STATUS_CONFIRMED_MALICIOUS,
    STATUS_BENIGN,
    STATUS_DUPLICATE,
    STATUS_UNRESOLVED,
    STATUS_PROMOTED,
    STATUS_DEPRECATED,
)

#: System-computed statuses (the detector funnel). Everything else needs a human.
SYSTEM_STATUSES = frozenset({STATUS_CANDIDATE, STATUS_NEEDS_REVIEW})
#: Statuses that carry a human decision.
REVIEWED_STATUSES = frozenset({
    STATUS_CONFIRMED_VALID, STATUS_CONFIRMED_MALICIOUS, STATUS_BENIGN,
    STATUS_DUPLICATE, STATUS_UNRESOLVED,
})
#: Statuses that may be promoted into durable risk intelligence.
PROMOTABLE_STATUSES = frozenset({STATUS_CONFIRMED_VALID, STATUS_CONFIRMED_MALICIOUS})
#: Statuses shown in the open review queue.
QUEUE_STATUSES = frozenset({STATUS_NEEDS_REVIEW, STATUS_UNRESOLVED})

Verdict = Literal["valid", "malicious", "benign", "duplicate", "unresolved"]
VERDICT_STATUS: dict[str, str] = {
    "valid": STATUS_CONFIRMED_VALID,
    "malicious": STATUS_CONFIRMED_MALICIOUS,
    "benign": STATUS_BENIGN,
    "duplicate": STATUS_DUPLICATE,
    "unresolved": STATUS_UNRESOLVED,
}
#: Verdicts that mean "the detector found something real" (calibration numerator).
USEFUL_VERDICTS = frozenset({"valid", "malicious"})
#: Verdicts that mean "the detector produced noise" (calibration penalty).
NOISE_VERDICTS = frozenset({"benign", "duplicate"})

SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")

# ── Thresholds shared by the scoring layer ──────────────────────────────────
NEEDS_REVIEW_CONFIDENCE = 0.4
NEEDS_REVIEW_NOVELTY = 0.3
#: After this many consecutive discovery runs without re-observation an open
#: pattern is deprecated automatically (reviewed patterns are left alone).
STALE_AFTER_RUNS = 6
MAX_EVIDENCE_REFS = 25
MAX_AFFECTED_ENTITIES = 500


def content_hash(payload: Any, length: int = 24) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:length]


def signature_hash(kind: str, signature: dict[str, Any]) -> str:
    return content_hash({"kind": kind, "signature": signature}, 32)


def pattern_id(tenant_id: str, kind: str, sig_hash: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}\x00{kind}\x00{sig_hash}".encode()).hexdigest()[:24]
    return f"{tenant_id}:pat:{digest}"


def size_bucket(n: int) -> int:
    """Order-of-magnitude bucket (log2). A reviewer's decision about a 5-entity
    pattern does not silently carry over to the same pattern at 500 entities."""
    return int(math.log2(n)) if n > 0 else 0


@dataclass
class EvidenceItem:
    """One line of support for a pattern.

    ``basis`` is ``observed`` only when the item restates a recorded fact
    (e.g. "these events exist"); every statistical judgement is ``inferred``.
    ``strength`` is a weight, not a probability.
    """

    type: str
    basis: Literal["observed", "inferred"]
    strength: float
    detail: dict[str, Any] = field(default_factory=dict)
    source_event_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "basis": self.basis,
            "strength": round(min(max(self.strength, 0.0), 1.0), 3),
            "detail": self.detail,
            "source_event_refs": list(dict.fromkeys(self.source_event_refs))[:MAX_EVIDENCE_REFS],
        }


@dataclass
class RawPattern:
    """What a detector returns before scoring and lifecycle are applied."""

    kind: str
    signature: dict[str, Any]
    title: str
    summary: str
    affected_entities: list[str]
    evidence: list[EvidenceItem]
    occurrence_count: int
    first_observed_at: Optional[datetime]
    last_observed_at: Optional[datetime]
    risk_categories: list[str] = field(default_factory=list)
    competing_explanations: list[dict[str, str]] = field(default_factory=list)
    #: Detector-local novelty in [0, 1] (1 = never seen in the tenant baseline).
    novelty: float = 1.0
    #: Baseline comparison numbers (expected vs observed, lift, z ...).
    baseline: dict[str, Any] = field(default_factory=dict)
    episode_count: int = 0
    detector: str = ""
    #: Member pattern ids (cross-domain composites only).
    member_pattern_ids: list[str] = field(default_factory=list)

    @property
    def signature_hash(self) -> str:
        return signature_hash(self.kind, self.signature)


def entity_ref(entity_key: str) -> dict[str, str]:
    """``"user:u1"`` -> ``{"kind": "user", "id": "u1"}``."""
    kind, _, ident = entity_key.partition(":")
    return {"kind": kind or "unknown", "id": ident or entity_key, "key": entity_key}


# ── API bodies ───────────────────────────────────────────────────────────────

class DiscoveryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window_hours: Optional[int] = Field(default=None, ge=1, le=24 * 90)
    max_events: Optional[int] = Field(default=None, ge=10, le=200_000)
    kinds: Optional[list[str]] = None
    #: Inline evidence (raw events) to analyse instead of / in addition to the
    #: tenant event store. Same shape as analytics event rows.
    events: Optional[list[dict[str, Any]]] = Field(default=None, max_length=50_000)
    #: Optional graph edges ``{source, target, type, source_kind?, target_kind?}``.
    edges: Optional[list[dict[str, Any]]] = Field(default=None, max_length=100_000)
    include_store: bool = True


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: Any
    event_type: Optional[str] = Field(default=None, max_length=200)
    text: Optional[str] = Field(default=None, max_length=100_000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Verdict
    reason: str = Field(..., min_length=10, max_length=2000)
    duplicate_of: Optional[str] = Field(default=None, max_length=300)


class PromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=10, max_length=2000)


class DeprecateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=10, max_length=2000)
