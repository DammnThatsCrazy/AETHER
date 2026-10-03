"""Identity Continuity Observability — metrics, traces, and decision logs.

Every identity decision log includes:
- tenant_id
- source_system_id
- source_identity_id
- candidate_entity_ids
- decision_type
- confidence
- vetoes
- policy_version
- graph_version_before
- graph_version_after
- projection_jobs_created

No PII in raw logs unless explicitly protected and redacted.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Optional

from shared.logger.logger import MetricsCollector, get_logger, metrics as shared_metrics

logger = get_logger("aether.identity.observability")

# ── Metrics counters (blueprint §19.1) ──────────────────────────────────────

class IdentityMetrics:
    """Counters and histograms for identity continuity runtime."""

    def __init__(self, collector: Optional[MetricsCollector] = None) -> None:
        self._collector = collector or shared_metrics
        self.reset()

    def reset(self) -> None:
        """Reset all counters (for tests)."""
        self.source_identity_created = 0
        self.claim_created = 0
        self.resolve_total = 0
        self.resolve_resolved = 0
        self.resolve_provisional = 0
        self.resolve_review_required = 0
        self.resolve_conflicted = 0
        self.resolve_suppressed = 0
        self.resolve_rejected = 0
        self.merge_auto = 0
        self.merge_manual = 0
        self.merge_blocked = 0
        self.split_candidate = 0
        self.split_executed = 0
        self.veto_total = 0
        self.cross_tenant_block = 0
        self.projection_restatement_queued = 0
        self.projection_restatement_failed = 0
        self.sdk_heartbeat_received = 0
        self.sdk_identify_received = 0
        self.connector_backfill_resolved = 0
        self.latency_samples: list[float] = []
        self.restatement_latency_samples: list[float] = []

    def record_source_identity_created(self) -> None:
        self.source_identity_created += 1
        self._collector.increment("identity.source_identity.created.count")

    def record_claim_created(self) -> None:
        self.claim_created += 1
        self._collector.increment("identity.claim.created.count")

    def record_resolution(
        self,
        outcome: str,
    ) -> None:
        """Record a resolution outcome (resolved, provisional, review_required, etc.)."""
        self.resolve_total += 1
        safe_outcome = outcome if outcome in {
            "resolved", "provisional", "review_required", "conflicted", "suppressed", "rejected"
        } else "other"
        self._collector.increment("identity.resolve.count")
        outcome_map = {
            "resolved": "resolve_resolved",
            "provisional": "resolve_provisional",
            "review_required": "resolve_review_required",
            "conflicted": "resolve_conflicted",
            "suppressed": "resolve_suppressed",
            "rejected": "resolve_rejected",
        }
        attr = outcome_map.get(outcome)
        if attr and hasattr(self, attr):
            setattr(self, attr, getattr(self, attr) + 1)
            self._collector.increment(f"identity.resolve.{outcome}.count")

    def record_merge(
        self,
        merge_type: str,
    ) -> None:
        """Record a merge (auto, manual, blocked)."""
        if merge_type == "auto":
            self.merge_auto += 1
        elif merge_type == "manual":
            self.merge_manual += 1
        elif merge_type == "blocked":
            self.merge_blocked += 1
        else:
            merge_type = "other"
        if merge_type in {"auto", "manual", "blocked"}:
            self._collector.increment(f"identity.merge.{merge_type}.count")

    def record_split(self, event: str) -> None:
        """Record a split event (candidate, executed)."""
        if event == "candidate":
            self.split_candidate += 1
        elif event == "executed":
            self.split_executed += 1
        else:
            event = "other"
        if event in {"candidate", "executed"}:
            self._collector.increment(f"identity.split.{event}.count")

    def record_veto(self) -> None:
        self.veto_total += 1
        self._collector.increment("identity.veto.count")

    def record_cross_tenant_block(self) -> None:
        self.cross_tenant_block += 1
        self._collector.increment("identity.cross_tenant_block.count")

    def record_projection_restatement(self, status: str) -> None:
        safe_status = status if status in {"queued", "running", "completed", "failed", "unsupported"} else "other"
        if safe_status == "queued":
            self.projection_restatement_queued += 1
            self._collector.increment("identity.projection_restatement.queued.count")
        if status == "failed":
            self.projection_restatement_failed += 1
            self._collector.increment("identity.projection_restatement.failed.count")

    def record_sdk_heartbeat(self) -> None:
        self.sdk_heartbeat_received += 1
        self._collector.increment("sdk.heartbeat.received.count")

    def record_sdk_identify(self) -> None:
        self.sdk_identify_received += 1
        self._collector.increment("sdk.identify.received.count")

    def record_connector_backfill(self) -> None:
        self.connector_backfill_resolved += 1
        self._collector.increment("connector.backfill.identity_resolved.count")

    def record_resolution_latency(self, latency_ms: float) -> None:
        self.latency_samples.append(latency_ms)
        self._collector.timing("identity.resolution.latency_ms", latency_ms)

    def record_restatement_latency(self, latency_ms: float) -> None:
        self.restatement_latency_samples.append(latency_ms)
        self._collector.timing("identity.restatement.latency_ms", latency_ms)

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all metrics."""
        return {
            "source_identity_created": self.source_identity_created,
            "claim_created": self.claim_created,
            "resolve_total": self.resolve_total,
            "resolve_resolved": self.resolve_resolved,
            "resolve_provisional": self.resolve_provisional,
            "resolve_review_required": self.resolve_review_required,
            "resolve_conflicted": self.resolve_conflicted,
            "resolve_suppressed": self.resolve_suppressed,
            "resolve_rejected": self.resolve_rejected,
            "merge_auto": self.merge_auto,
            "merge_manual": self.merge_manual,
            "merge_blocked": self.merge_blocked,
            "split_candidate": self.split_candidate,
            "split_executed": self.split_executed,
            "veto_total": self.veto_total,
            "cross_tenant_block": self.cross_tenant_block,
            "projection_restatement_queued": self.projection_restatement_queued,
            "projection_restatement_failed": self.projection_restatement_failed,
            "sdk_heartbeat_received": self.sdk_heartbeat_received,
            "sdk_identify_received": self.sdk_identify_received,
            "connector_backfill_resolved": self.connector_backfill_resolved,
            "avg_resolution_latency_ms": (
                sum(self.latency_samples) / len(self.latency_samples)
                if self.latency_samples else 0.0
            ),
            "avg_restatement_latency_ms": (
                sum(self.restatement_latency_samples) / len(self.restatement_latency_samples)
                if self.restatement_latency_samples else 0.0
            ),
        }


# Per-module metrics instances (use dependency injection in production)
identity_metrics = IdentityMetrics()


# ── Decision logging (blueprint §19.3) ──────────────────────────────────────

def log_identity_decision(
    tenant_id: str,
    source_system_id: str,
    source_identity_id: str,
    candidate_entity_ids: list[str],
    decision_type: str,
    confidence: float,
    vetoes: list[dict],
    policy_version: str,
    graph_version_before: Optional[str],
    graph_version_after: Optional[str],
    projection_jobs_created: int,
    redact_pii: bool = True,
) -> None:
    """Log an identity decision with all required fields.

    No PII in raw logs unless explicitly protected and redacted.
    """
    logger.info(
        "identity.decision",
        extra={
            "tenant_id": tenant_id,
            "source_system_id": source_system_id,
            "source_identity_id": source_identity_id,
            "candidate_entity_ids": candidate_entity_ids,
            "decision_type": decision_type,
            "confidence": confidence,
            "vetoes": vetoes if not redact_pii else [{"type": v.get("veto_type", "unknown")} for v in vetoes],
            "policy_version": policy_version,
            "graph_version_before": graph_version_before,
            "graph_version_after": graph_version_after,
            "projection_jobs_created": projection_jobs_created,
        },
    )


# ── Trace path (blueprint §19.2) ────────────────────────────────────────────

class IdentityTrace:
    """Simple trace context for the identity resolution path."""

    def __init__(
        self, tenant_id: str, source_system_id: str, *, correlation_id: Optional[str] = None
    ) -> None:
        self.tenant_id = tenant_id
        self.source_system_id = source_system_id
        if correlation_id:
            seed = f"{tenant_id}\x00{correlation_id}".encode("utf-8")
            self.trace_id = hashlib.sha256(seed).hexdigest()[:32]
        else:
            self.trace_id = str(uuid.uuid4())
        self.steps: list[dict[str, Any]] = []
        self.start_time = time.time()

    def add_step(self, step: str, details: Optional[dict[str, Any]] = None) -> None:
        """Add and emit one PII-safe trace step."""
        elapsed = time.time() - self.start_time
        safe_details = _safe_trace_details(details or {})
        record = {
            "step": step,
            "timestamp": elapsed,
            "details": safe_details,
        }
        self.steps.append(record)
        try:
            logger.info(
                "identity.trace.step",
                extra={
                    "identity_trace_id": self.trace_id,
                    "identity_trace_step": step,
                    "identity_trace_sequence": len(self.steps),
                    "identity_trace_elapsed_ms": elapsed * 1000,
                    "tenant_id": self.tenant_id,
                    "source_system_id": self.source_system_id,
                    "identity_trace_details": safe_details,
                },
            )
            shared_metrics.increment("identity.trace.step", labels={"step": step})
        except Exception:
            # Telemetry exporters must not break identity resolution.
            pass

    def ingestion_receive(self) -> None:
        self.add_step("ingestion.receive")

    def source_identity_register(self, source_identity_id: str) -> None:
        self.add_step("source_identity.register", {"source_identity_id": source_identity_id})

    def claims_normalize(self, claim_count: int) -> None:
        self.add_step("claims.normalize", {"claim_count": claim_count})

    def identity_resolve(self, outcome: str, confidence: float) -> None:
        self.add_step("identity.resolve", {"outcome": outcome, "confidence": confidence})

    def policy_score(self, score: float, tier: str) -> None:
        self.add_step("policy.score", {"score": score, "tier": tier})

    def veto_evaluate(self, veto_count: int) -> None:
        self.add_step("veto.evaluate", {"veto_count": veto_count})

    def decision_write(self, decision_id: str) -> None:
        self.add_step("decision.write", {"decision_id": decision_id})

    def graph_version_create(self, version_id: str) -> None:
        self.add_step("graph_version.create", {"version_id": version_id})

    def projection_restatement_queue(self, job_ids: list[str]) -> None:
        self.add_step("projection_restatement.queue", {"job_count": len(job_ids)})

    def profile_360_update(self, entity_ids: list[str]) -> None:
        self.add_step("profile_360.update", {"entity_count": len(entity_ids)})

    def get_trace_summary(self) -> dict[str, Any]:
        """Get the full trace summary."""
        return {
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "source_system_id": self.source_system_id,
            "duration_ms": (time.time() - self.start_time) * 1000,
            "steps": self.steps,
        }


_SAFE_TRACE_DETAIL_KEYS = frozenset({
    "source_identity_id", "claim_count", "outcome", "confidence", "score", "tier",
    "veto_count", "decision_id", "version_id", "job_count", "entity_count",
})


def _safe_trace_details(details: dict[str, Any]) -> dict[str, Any]:
    """Keep bounded diagnostic fields and discard arbitrary event/claim payloads."""
    safe: dict[str, Any] = {}
    for key in _SAFE_TRACE_DETAIL_KEYS:
        value = details.get(key)
        if value is None:
            continue
        if key in {"confidence", "score"}:
            try:
                safe[key] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
        elif key.endswith("_count"):
            if isinstance(value, int) and not isinstance(value, bool):
                safe[key] = max(0, value)
        else:
            text_value = str(value)
            if len(text_value) <= 160:
                safe[key] = text_value
    return safe
