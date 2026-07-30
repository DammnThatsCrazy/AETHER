"""Data-quality / intelligence-quality services.

Scores and findings exist only after a canonical monitor reports observations.
Missing evidence is represented explicitly; the service never manufactures a
healthy baseline or seeds drift records during a read.

Critical ``tenant_data_contamination`` drift escalates into the Security &
Governance audit ledger — it is never silently surfaced.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.logger.logger import get_logger

from services.data_quality.models import (
    QUALITY_DIMENSIONS,
    DriftEvent,
    IntelligenceQualityScore,
    now_iso,
    status_for_score,
)
from services.data_quality.repositories import (
    DriftEventRepository,
    IntelligenceQualityRepository,
)

logger = get_logger("aether.service.data_quality")

# Module-level repository singletons (shared in-memory store across instances).
_scores = IntelligenceQualityRepository()
_drift = DriftEventRepository()

# Route key → score field, so a dimension report can be looked up by its
# tenant-facing route segment (e.g. "events" → event_quality_score).
ROUTE_TO_DIMENSION: dict[str, str] = {
    "events": "event_quality_score",
    "schema": "schema_stability_score",
    "identity": "identity_resolution_score",
    "graph": "graph_quality_score",
    "profile": "profile_quality_score",
    "recommendations": "recommendation_quality_score",
    "outcomes": "outcome_feedback_quality_score",
    "playbooks": "playbook_quality_score",
}


# ═══════════════════════════════════════════════════════════════════════════
# Intelligence quality scoring
# ═══════════════════════════════════════════════════════════════════════════

class IntelligenceQualityService:
    """Computes per-dimension and overall intelligence-quality scores.

    Canonical monitors write snapshots through ``report_score`` and
    ``report_dimension``. Reads without a snapshot return insufficient evidence.
    """

    def __init__(self) -> None:
        self.repo = _scores

    # ── per-dimension reports ────────────────────────────────────────────────

    async def dimension_report(self, route_key: str, tenant_id: Optional[str]) -> dict[str, Any]:
        """Full metric report for one dimension, by tenant-facing route key."""
        dimension_field = ROUTE_TO_DIMENSION[route_key]
        key = f"dimension:{tenant_id or '*'}:{dimension_field}"
        report = await self.repo.find_by_id(key)
        if report:
            return {k: v for k, v in report.items() if not k.startswith("_")}
        return {
            "dimension": dimension_field,
            "tenant_id": tenant_id,
            "scope": "tenant" if tenant_id else "platform",
            "quality_score": None,
            "status": "unknown",
            "calculated_at": None,
            "availability": "insufficient_evidence",
        }

    async def contamination_report(self, tenant_id: Optional[str]) -> dict[str, Any]:
        key = f"dimension:{tenant_id or '*'}:contamination"
        report = await self.repo.find_by_id(key)
        if report:
            return {k: v for k, v in report.items() if not k.startswith("_")}
        return {
            "tenant_id": tenant_id,
            "scope": "tenant" if tenant_id else "platform",
            "contamination_score": None,
            "status": "unknown",
            "calculated_at": None,
            "availability": "insufficient_evidence",
        }

    # ── composite score ──────────────────────────────────────────────────────

    async def compute_score(self, tenant_id: Optional[str], scope: str = "tenant") -> dict[str, Any]:
        key = f"{scope}:{tenant_id or '*'}"
        stored = await self.repo.find_by_id(key)
        if stored:
            return {k: v for k, v in stored.items() if not k.startswith("_")}
        return IntelligenceQualityScore(
            tenant_id=tenant_id,
            scope=scope,
        ).model_dump() | {"availability": "insufficient_evidence"}

    async def overview(self, tenant_id: Optional[str], scope: str = "tenant") -> dict[str, Any]:
        score = await self.compute_score(tenant_id, scope)
        # Drift affecting this scope: tenant overview shows only that tenant's own
        # drift (platform-wide drift is internal and not surfaced to tenants).
        if tenant_id:
            drift = await drift_service.list(tenant_id=tenant_id)
        else:
            drift = await drift_service.list()
        active = [d for d in drift if d.get("status") in ("open", "acknowledged")]
        by_severity: dict[str, int] = {}
        for d in active:
            by_severity[d["severity"]] = by_severity.get(d["severity"], 0) + 1
        dimensions = {
            field: {
                "score": score.get(field),
                "status": (
                    status_for_score(score[field])
                    if isinstance(score.get(field), (int, float))
                    else "unknown"
                ),
            }
            for field in QUALITY_DIMENSIONS
        }
        return {
            "score": score,
            "dimensions": dimensions,
            "open_drift_event_count": len(active),
            "drift_by_severity": by_severity,
        }

    async def list_tenant_scores(self, tenant_ids: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Aggregate-only per-tenant scores for the Kyber tenants view.

        Returns scalar scores per tenant — never raw tenant-private payloads.
        """
        rows = await self.repo.find_many(limit=10000)
        out = [
            {
                "tenant_id": row.get("tenant_id"),
                "overall_intelligence_quality_score": row.get("overall_intelligence_quality_score"),
                "status": row.get("status", "unknown"),
                "calculated_at": row.get("calculated_at"),
            }
            for row in rows
            if row.get("scope") == "tenant"
            and row.get("tenant_id")
            and (tenant_ids is None or row.get("tenant_id") in tenant_ids)
            and isinstance(row.get("overall_intelligence_quality_score"), (int, float))
        ]
        return sorted(out, key=lambda r: r["overall_intelligence_quality_score"])

    # ── live-telemetry adapter ────────────────────────────────────────────────

    async def report_score(self, tenant_id: Optional[str], scope: str, scores: dict[str, float]) -> dict[str, Any]:
        """Override a computed snapshot with live values (deployment telemetry)."""
        key = f"{scope}:{tenant_id or '*'}"
        existing = await self.repo.find_by_id(key) or {}
        existing.update({k: v for k, v in scores.items() if k in QUALITY_DIMENSIONS})
        present = [existing.get(f) for f in QUALITY_DIMENSIONS if isinstance(existing.get(f), (int, float))]
        if present:
            overall = round(sum(present) / len(present), 4)
            existing["overall_intelligence_quality_score"] = overall
            existing["status"] = status_for_score(overall)
        existing.update({"tenant_id": tenant_id, "scope": scope, "calculated_at": now_iso(), "_key": key})
        await self.repo.insert(key, existing)
        return existing

    async def report_dimension(
        self,
        route_key: str,
        tenant_id: Optional[str],
        *,
        quality_score: float,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one authoritative monitor observation."""
        dimension_field = ROUTE_TO_DIMENSION[route_key]
        bounded = max(0.0, min(1.0, quality_score))
        key = f"dimension:{tenant_id or '*'}:{dimension_field}"
        record = {
            **metrics,
            "dimension": dimension_field,
            "tenant_id": tenant_id,
            "scope": "tenant" if tenant_id else "platform",
            "quality_score": bounded,
            "status": status_for_score(bounded),
            "calculated_at": now_iso(),
            "availability": "available",
            "_key": key,
        }
        await self.repo.insert(key, record)
        return {k: v for k, v in record.items() if not k.startswith("_")}


intelligence_quality_service = IntelligenceQualityService()


# ═══════════════════════════════════════════════════════════════════════════
# Drift events
# ═══════════════════════════════════════════════════════════════════════════

class DriftService:
    def __init__(self) -> None:
        self.repo = _drift

    async def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        drift_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        rows = await self.repo.find_many(limit=1000, sort_by="detected_at", sort_order="desc")
        if tenant_id is not None:
            rows = [r for r in rows if r.get("tenant_id") == tenant_id]
        if drift_type:
            rows = [r for r in rows if r.get("drift_type") == drift_type]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    async def get(self, drift_event_id: str) -> dict[str, Any] | None:
        return await self.repo.find_by_id(drift_event_id)

    async def _record_audit(
        self,
        event: DriftEvent,
        *,
        event_type: str,
        action: str,
        outcome: str,
        actor_id: str,
        actor_type: str,
    ) -> Optional[str]:
        """Best-effort escalation into the Security & Governance audit ledger.

        Never raises into the caller — audit failures must not break drift flow.
        Metadata is sanitized by the ledger before persistence (no secrets).
        """
        try:
            from services.security.audit_ledger import audit_ledger

            recorded = await audit_ledger.record(
                actor_id=actor_id,
                actor_type=actor_type,  # type: ignore[arg-type]
                event_type=event_type,
                resource_type="drift_event",
                resource_id=event.drift_event_id,
                action=action,
                outcome=outcome,  # type: ignore[arg-type]
                tenant_id=event.tenant_id,
                metadata={
                    "drift_type": event.drift_type,
                    "severity": event.severity,
                    "reason": event.reason,
                    "supporting_metrics": event.supporting_metrics,
                },
            )
            return recorded.audit_event_id
        except Exception as exc:  # pragma: no cover - audit must never break flow
            logger.warning(f"drift audit escalation failed: {exc}")
            return None

    async def create(self, data: dict[str, Any], *, actor: Optional[str] = None, actor_type: str = "system") -> dict[str, Any]:
        drift_id = data.get("drift_event_id") or f"drift_{uuid.uuid4().hex[:12]}"
        event = DriftEvent(drift_event_id=drift_id, **{k: v for k, v in data.items() if k != "drift_event_id"})
        # Critical/high tenant-data contamination escalates into Security/Governance.
        if event.drift_type == "tenant_data_contamination" and event.severity in ("high", "critical"):
            audit_id = await self._record_audit(
                event,
                event_type="data_quality_contamination_detected",
                action="detect",
                outcome="blocked",
                actor_id=actor or "data_quality_monitor",
                actor_type=actor_type,
            )
            event.escalated_audit_event_id = audit_id
        return await self.repo.insert(drift_id, event.model_dump())

    async def acknowledge(self, drift_event_id: str, *, actor: Optional[str] = None) -> dict[str, Any]:
        existing = await self.repo.find_by_id_or_fail(drift_event_id)
        existing.update({"status": "acknowledged", "acknowledged_at": now_iso(), "updated_at": now_iso()})
        return await self.repo.update(drift_event_id, existing)

    async def resolve(
        self,
        drift_event_id: str,
        *,
        actor: Optional[str] = None,
        actor_type: str = "olympus_operator",
        resolution_note: Optional[str] = None,
    ) -> dict[str, Any]:
        existing = await self.repo.find_by_id_or_fail(drift_event_id)
        existing.update({"status": "resolved", "resolved_at": now_iso(), "updated_at": now_iso()})
        if resolution_note:
            metrics = dict(existing.get("supporting_metrics") or {})
            metrics["resolution_note"] = resolution_note
            existing["supporting_metrics"] = metrics
        stored = await self.repo.update(drift_event_id, existing)
        # Drift resolution is a sensitive governance action → audit it.
        await self._record_audit(
            DriftEvent(**stored),
            event_type="data_quality_drift_resolution",
            action="resolve",
            outcome="allowed",
            actor_id=actor or "system",
            actor_type=actor_type,
        )
        return stored

    async def detect_contamination(
        self,
        *,
        tenant_id: Optional[str],
        severity: str,
        reason: str,
        supporting_metrics: dict[str, Any],
        recommended_action: str = "Quarantine affected records and investigate tenant scoping.",
        actor: Optional[str] = None,
    ) -> dict[str, Any]:
        """Adapter for upstream detectors: records a contamination drift (which
        escalates into the audit ledger for high/critical severity)."""
        return await self.create(
            {
                "tenant_id": tenant_id,
                "drift_type": "tenant_data_contamination",
                "severity": severity,
                "source": "contamination_detector",
                "reason": reason,
                "supporting_metrics": supporting_metrics,
                "recommended_action": recommended_action,
            },
            actor=actor,
            actor_type="system",
        )


drift_service = DriftService()
