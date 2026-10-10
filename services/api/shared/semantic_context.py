"""
Aether Shared — Semantic Context Intelligence Layer primitives.

These primitives are intentionally additive: they attach a compact semantic
context envelope to existing events, records, lake rows, or graph vertices
without replacing SIRs, entity records, embeddings, or graph schemas.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional


class SemanticLayer(str, Enum):
    """Purpose-oriented semantic layers ordered by cost and persistence horizon."""

    PULSE = "pulse"
    SESSION = "session"
    SEMANTIC = "semantic"
    WORKFLOW = "workflow"
    RELATIONAL = "relational"
    BEHAVIORAL = "behavioral"
    ARCHITECTURAL = "architectural"
    SYSTEMIC = "systemic"


class PersistenceClass(str, Enum):
    """Server-controlled lifecycle classes for semantic persistence."""

    TRANSIENT = "transient"
    SHORT_TTL = "short_ttl"
    MEDIUM_TTL = "medium_ttl"
    LONG_DECAYING = "long_decaying"
    SUMMARIZED = "summarized"
    EPHEMERAL_DEEP = "ephemeral_deep"


class RelationshipKind(str, Enum):
    """Semantic relationship types supported by the additive layer."""

    USES = "USES"
    MODIFIES = "MODIFIES"
    INFLUENCES = "INFLUENCES"
    DERIVES_FROM = "DERIVES_FROM"
    CO_OCCURS_WITH = "CO_OCCURS_WITH"
    DEPENDS_ON = "DEPENDS_ON"
    FREQUENTLY_PRECEDES = "FREQUENTLY_PRECEDES"
    CAUSED_DRIFT_IN = "CAUSED_DRIFT_IN"
    SEMANTICALLY_SIMILAR = "SEMANTICALLY_SIMILAR"
    WORKFLOW_PARTNER = "WORKFLOW_PARTNER"


_DEFAULT_TTLS: dict[PersistenceClass, int | None] = {
    PersistenceClass.TRANSIENT: 15 * 60,
    PersistenceClass.SHORT_TTL: 7 * 24 * 60 * 60,
    PersistenceClass.MEDIUM_TTL: 60 * 24 * 60 * 60,
    PersistenceClass.LONG_DECAYING: 365 * 24 * 60 * 60,
    PersistenceClass.SUMMARIZED: None,
    PersistenceClass.EPHEMERAL_DEEP: 60 * 60,
}

_LAYER_DEFAULTS: dict[SemanticLayer, tuple[PersistenceClass, bool, int]] = {
    SemanticLayer.PULSE: (PersistenceClass.TRANSIENT, False, 4),
    SemanticLayer.SESSION: (PersistenceClass.SHORT_TTL, False, 12),
    SemanticLayer.SEMANTIC: (PersistenceClass.MEDIUM_TTL, True, 24),
    SemanticLayer.WORKFLOW: (PersistenceClass.MEDIUM_TTL, False, 32),
    SemanticLayer.RELATIONAL: (PersistenceClass.LONG_DECAYING, False, 48),
    SemanticLayer.BEHAVIORAL: (PersistenceClass.SUMMARIZED, False, 24),
    SemanticLayer.ARCHITECTURAL: (PersistenceClass.SUMMARIZED, False, 32),
    SemanticLayer.SYSTEMIC: (PersistenceClass.SUMMARIZED, False, 16),
}


@dataclass(frozen=True)
class SemanticDelta:
    """Compressed change statement persisted instead of full semantic payloads."""

    field: str
    operation: str
    summary: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "operation": self.operation,
            "summary": self.summary,
            "confidence": round(_clamp01(self.confidence), 4),
        }


@dataclass(frozen=True)
class RelationshipRef:
    """Reference to a weighted relationship without duplicating graph edges."""

    kind: RelationshipKind
    target_ref: str
    strength: float = 1.0
    confidence: float = 1.0
    graph_edge_ref: Optional[str] = None
    expires_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind.value,
            "target_ref": self.target_ref,
            "strength": round(_clamp01(self.strength), 4),
            "confidence": round(_clamp01(self.confidence), 4),
        }
        if self.graph_edge_ref:
            out["graph_edge_ref"] = self.graph_edge_ref
        if self.expires_at:
            out["expires_at"] = self.expires_at
        return out


@dataclass(frozen=True)
class PersistencePolicy:
    """Adaptive persistence controls owned by backend enrichment services."""

    persistence_class: PersistenceClass
    ttl_seconds: Optional[int] = None
    decay_rate: float = 0.0
    summarize_after_seconds: Optional[int] = None
    max_relationship_refs: int = 16
    max_payload_keys: int = 24

    def to_dict(self) -> dict[str, Any]:
        ttl = (
            _DEFAULT_TTLS[self.persistence_class]
            if self.ttl_seconds is None
            else self.ttl_seconds
        )
        out: dict[str, Any] = {
            "class": self.persistence_class.value,
            "ttl_seconds": ttl,
            "decay_rate": round(max(self.decay_rate, 0.0), 6),
            "max_relationship_refs": self.max_relationship_refs,
            "max_payload_keys": self.max_payload_keys,
        }
        if self.summarize_after_seconds is not None:
            out["summarize_after_seconds"] = self.summarize_after_seconds
        return out


@dataclass(frozen=True)
class SemanticContextEnvelope:
    """
    Compact, additive semantic wrapper for existing Aether records.

    The envelope carries layer, confidence, temporal weighting, relationship
    references, deltas, workflow links, and server-owned enrichment policy. It
    never requires a new embedding; vector references are pointers to existing
    vectors when reuse is possible.
    """

    primary_layer: SemanticLayer
    layers: tuple[SemanticLayer, ...] = field(default_factory=tuple)
    confidence: float = 0.5
    temporal_weight: float = 1.0
    recency_score: float = 1.0
    relationship_refs: tuple[RelationshipRef, ...] = field(default_factory=tuple)
    semantic_deltas: tuple[SemanticDelta, ...] = field(default_factory=tuple)
    compressed_payload: dict[str, Any] = field(default_factory=dict)
    workflow_refs: tuple[str, ...] = field(default_factory=tuple)
    episode_refs: tuple[str, ...] = field(default_factory=tuple)
    enrichment: dict[str, Any] = field(default_factory=dict)
    persistence: Optional[PersistencePolicy] = None
    vector_ref: Optional[str] = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.layers:
            object.__setattr__(self, "layers", (self.primary_layer,))
        if self.primary_layer not in self.layers:
            object.__setattr__(self, "layers", (self.primary_layer, *self.layers))
        if self.persistence is None:
            persistence_class, vectorize, payload_cap = _LAYER_DEFAULTS[self.primary_layer]
            object.__setattr__(
                self,
                "persistence",
                PersistencePolicy(
                    persistence_class=persistence_class,
                    max_payload_keys=payload_cap,
                    decay_rate=(
                        0.002
                        if persistence_class == PersistenceClass.LONG_DECAYING
                        else 0.0
                    ),
                ),
            )
            if "vectorize" not in self.enrichment:
                enrichment = {**self.enrichment, "vectorize": vectorize}
                object.__setattr__(self, "enrichment", enrichment)

    @property
    def stable_hash(self) -> str:
        """Stable cache key for deduplication and vector reuse."""
        base = "|".join(
            [
                self.primary_layer.value,
                str(round(_clamp01(self.confidence), 4)),
                *sorted(str(v) for v in self.workflow_refs),
                *sorted(f"{d.field}:{d.operation}:{d.summary}" for d in self.semantic_deltas),
                *sorted(f"{k}:{self.compressed_payload[k]}" for k in self.compressed_payload),
            ]
        )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]

    def should_vectorize(self, threshold: float = 0.72) -> bool:
        """Return whether this envelope is valuable enough for vector generation."""
        if self.vector_ref:
            return False
        if self.enrichment.get("vectorize") is False:
            return False
        return _clamp01(self.confidence) >= threshold and self.primary_layer in {
            SemanticLayer.SEMANTIC,
            SemanticLayer.WORKFLOW,
            SemanticLayer.ARCHITECTURAL,
            SemanticLayer.SYSTEMIC,
        }

    def pruned(self) -> "SemanticContextEnvelope":
        """Apply graph-density and payload caps before persistence."""
        policy = self.persistence or PersistencePolicy(PersistenceClass.TRANSIENT)
        refs = tuple(
            sorted(
                self.relationship_refs,
                key=lambda r: (r.confidence * r.strength, r.target_ref),
                reverse=True,
            )[: policy.max_relationship_refs]
        )
        payload = dict(list(self.compressed_payload.items())[: policy.max_payload_keys])
        return SemanticContextEnvelope(
            primary_layer=self.primary_layer,
            layers=self.layers,
            confidence=self.confidence,
            temporal_weight=self.temporal_weight,
            recency_score=self.recency_score,
            relationship_refs=refs,
            semantic_deltas=self.semantic_deltas,
            compressed_payload=payload,
            workflow_refs=self.workflow_refs,
            episode_refs=self.episode_refs,
            enrichment=self.enrichment,
            persistence=policy,
            vector_ref=self.vector_ref,
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        policy = self.persistence or PersistencePolicy(PersistenceClass.TRANSIENT)
        refs = tuple(
            sorted(
                self.relationship_refs,
                key=lambda r: (r.confidence * r.strength, r.target_ref),
                reverse=True,
            )[: policy.max_relationship_refs]
        )
        payload = dict(list(self.compressed_payload.items())[: policy.max_payload_keys])
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "primary_layer": self.primary_layer.value,
            "layers": [layer.value for layer in self.layers],
            "confidence": round(_clamp01(self.confidence), 4),
            "temporal_weight": round(max(self.temporal_weight, 0.0), 4),
            "recency_score": round(_clamp01(self.recency_score), 4),
            "stable_hash": self.stable_hash,
            "persistence": policy.to_dict(),
        }
        if refs:
            out["relationship_refs"] = [ref.to_dict() for ref in refs]
        if self.semantic_deltas:
            out["semantic_deltas"] = [delta.to_dict() for delta in self.semantic_deltas]
        if payload:
            out["compressed_payload"] = payload
        if self.workflow_refs:
            out["workflow_refs"] = list(self.workflow_refs)
        if self.episode_refs:
            out["episode_refs"] = list(self.episode_refs)
        if self.enrichment:
            out["enrichment"] = self.enrichment
        if self.vector_ref:
            out["vector_ref"] = self.vector_ref
        return out

    def attach_to(self, record: dict[str, Any], field_name: str = "semantic_context") -> dict[str, Any]:
        """Return a copy of an existing record with an additive envelope field."""
        return {**record, field_name: self.to_dict()}


@dataclass(frozen=True)
class SemanticEpisode:
    """Lightweight semantic workflow narrative inferred from nearby signals."""

    episode_id: str
    label: str
    entity_refs: tuple[str, ...]
    workflow_refs: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.5
    relationship_refs: tuple[RelationshipRef, ...] = field(default_factory=tuple)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "label": self.label,
            "entity_refs": list(self.entity_refs),
            "workflow_refs": list(self.workflow_refs),
            "confidence": round(_clamp01(self.confidence), 4),
            "relationship_refs": [ref.to_dict() for ref in self.relationship_refs],
            "summary": self.summary,
        }


class SemanticEpisodeHeuristics:
    """Rule-driven initial episode inference; no retraining required."""

    _LABEL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Authentication Hardening Workflow", ("auth", "jwt", "oauth", "session", "login")),
        ("API Migration Workflow", ("api", "route", "client", "migration", "version")),
        ("Dependency Stabilization Workflow", ("dependency", "lock", "package", "cargo", "requirements")),
        ("Refactor Workflow", ("refactor", "rename", "extract", "cleanup", "module")),
        ("Semantic Drift Correction Workflow", ("drift", "schema", "contract", "compat", "regression")),
    )

    @classmethod
    def infer(cls, signals: Iterable[dict[str, Any]], tenant_id: str = "") -> Optional[SemanticEpisode]:
        compact = [s for s in signals if s]
        if len(compact) < 2:
            return None

        entity_refs = tuple(dict.fromkeys(str(s.get("entity_ref") or s.get("path") or s.get("id")) for s in compact))
        joined = " ".join(str(s.get("text") or s.get("event") or s.get("path") or "") for s in compact).lower()
        label = "Operational Continuity Workflow"
        rule_hits = 0
        for candidate, terms in cls._LABEL_RULES:
            hits = sum(1 for term in terms if term in joined)
            if hits > rule_hits:
                label = candidate
                rule_hits = hits

        temporal_score = _temporal_compactness(compact)
        co_mod_score = min(len(entity_refs) / 4, 1.0)
        recurrence_score = min(sum(1 for s in compact if s.get("workflow_ref")) / len(compact), 1.0)
        confidence = 0.35 + (0.25 * temporal_score) + (0.2 * co_mod_score) + (0.2 * recurrence_score)
        if rule_hits:
            confidence += min(rule_hits * 0.05, 0.15)

        edge_refs = tuple(
            RelationshipRef(
                kind=RelationshipKind.WORKFLOW_PARTNER,
                target_ref=ref,
                strength=min(0.4 + co_mod_score, 1.0),
                confidence=confidence,
            )
            for ref in entity_refs[:8]
        )
        workflow_refs = tuple(
            dict.fromkeys(str(s.get("workflow_ref")) for s in compact if s.get("workflow_ref"))
        )
        seed = "|".join([tenant_id, label, *entity_refs, *workflow_refs])
        episode_id = f"se_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"
        return SemanticEpisode(
            episode_id=episode_id,
            label=label,
            entity_refs=entity_refs,
            workflow_refs=workflow_refs,
            confidence=_clamp01(confidence),
            relationship_refs=edge_refs,
            summary=f"{label} across {len(entity_refs)} semantic entities.",
        )


def _temporal_compactness(signals: list[dict[str, Any]]) -> float:
    timestamps = [float(s["timestamp_ms"]) for s in signals if isinstance(s.get("timestamp_ms"), (int, float))]
    if len(timestamps) < 2:
        return 0.5
    span_minutes = (max(timestamps) - min(timestamps)) / 60000
    if span_minutes <= 15:
        return 1.0
    if span_minutes >= 240:
        return 0.15
    return 1.0 - ((span_minutes - 15) / 225 * 0.85)


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)
