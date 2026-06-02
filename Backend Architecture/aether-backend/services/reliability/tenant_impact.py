"""Tenant impact analysis (Phase 8).

Computes how incidents and degraded pipelines affect individual tenants, reading
from existing intelligence/billing repositories. Produces two strictly-separated
projections:

* ``tenant_safe_summary`` — what a tenant may see in Aether (no infra internals,
  single-tenant only).
* ``internal_summary`` — full cross-tenant detail for Kyber operators only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.intelligence.repositories import (
    ActionDispatchRepository,
    ActionIntegrationConfigRepository,
    AuditExportRepository,
    OutcomeRepository,
    RecommendationRepository,
    RevenueMeteringEventRepository,
)
from services.reliability.models import TenantStatusSummary, now_iso
from services.reliability.service import incident_service

_recommendations = RecommendationRepository()
_dispatches = ActionDispatchRepository()
_outcomes = OutcomeRepository()
_audit_exports = AuditExportRepository()
_metering = RevenueMeteringEventRepository()
_integrations = ActionIntegrationConfigRepository()

# Status thresholds for tenant data freshness (seconds).
_FRESH_SECONDS = 3600
_STALE_SECONDS = 86400


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_time(rows: list[dict[str, Any]], *keys: str) -> datetime | None:
    latest: datetime | None = None
    for row in rows:
        for key in keys:
            parsed = _parse_time(row.get(key))
            if parsed and (latest is None or parsed > latest):
                latest = parsed
    return latest


def _freshness_label(latest: datetime | None) -> str:
    if latest is None:
        return "unknown"
    age = (datetime.now(timezone.utc) - latest).total_seconds()
    if age <= _FRESH_SECONDS:
        return "fresh"
    if age <= _STALE_SECONDS:
        return "delayed"
    return "stale"


class TenantImpactAnalyzer:
    async def _tenant_incidents(self, tenant_id: str) -> list[dict[str, Any]]:
        incidents = await incident_service.list()
        return [i for i in incidents if tenant_id in (i.get("affected_tenants") or [])]

    async def compute(self, tenant_id: str) -> dict[str, Any]:
        """Full per-tenant impact detail (internal). Strictly single-tenant scoped."""
        recommendations = await _recommendations.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        dispatches = await _dispatches.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        outcomes = await _outcomes.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        audit_exports = await _audit_exports.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        metering = await _metering.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        integrations = await _integrations.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        incidents = await self._tenant_incidents(tenant_id)

        failed_dispatches = [d for d in dispatches if d.get("status") in ("failed", "dead_letter")]
        delayed_outcomes = [o for o in outcomes if o.get("status") in ("pending", "delayed")]
        failed_audit_exports = [a for a in audit_exports if a.get("status") in ("failed", "error")]
        missed_billing = [m for m in metering if m.get("status") in ("failed", "missed", "error")]
        unhealthy_integrations = [i for i in integrations if i.get("status") in ("failed", "error", "disconnected")]
        affected_modules = sorted({m for inc in incidents for m in (inc.get("affected_modules") or [])})

        data_latest = _latest_time(recommendations + outcomes, "updated_at", "created_at", "computed_at")
        rec_latest = _latest_time(recommendations, "created_at", "updated_at")

        return {
            "tenant_id": tenant_id,
            "active_incident_count": sum(1 for i in incidents if i.get("status") not in ("resolved", "closed")),
            "affected_modules": affected_modules,
            "recommendations_total": len(recommendations),
            "failed_dispatches": len(failed_dispatches),
            "delayed_outcomes": len(delayed_outcomes),
            "missed_billing_events": len(missed_billing),
            "failed_audit_exports": len(failed_audit_exports),
            "unhealthy_integrations": len(unhealthy_integrations),
            "data_freshness": _freshness_label(data_latest),
            "recommendation_freshness": _freshness_label(rec_latest),
            "incidents": incidents,
        }

    async def tenant_safe_summary(self, tenant_id: str) -> dict[str, Any]:
        """Tenant-safe projection for Aether. No infra internals, single tenant."""
        detail = await self.compute(tenant_id)
        active_incidents = detail["active_incident_count"]
        data_fresh = detail["data_freshness"]

        if active_incidents > 0 or data_fresh == "stale":
            overall = "degraded" if data_fresh != "stale" else "critical"
        elif data_fresh == "delayed":
            overall = "degraded"
        elif data_fresh == "unknown":
            overall = "unknown"
        else:
            overall = "healthy"

        integration_status = "degraded" if detail["unhealthy_integrations"] else "operational"
        audit_status = "delayed" if detail["failed_audit_exports"] else "operational"
        rec_status = detail["recommendation_freshness"]
        outcome_status = "delayed" if detail["delayed_outcomes"] else "operational"

        summary = TenantStatusSummary(
            tenant_id=tenant_id,
            overall_status=overall,  # type: ignore[arg-type]
            data_freshness=data_fresh,
            active_incidents=active_incidents,
            integration_status=integration_status,
            audit_export_status=audit_status,
            recommendation_status=rec_status,
            outcome_capture_status=outcome_status,
            updated_at=now_iso(),
        )
        return summary.model_dump()

    async def tenant_incidents_safe(self, tenant_id: str) -> dict[str, Any]:
        """Tenant-impacting incidents, stripped of internal fields."""
        incidents = await self._tenant_incidents(tenant_id)
        safe = [self._safe_incident(i) for i in incidents]
        return {
            "active": [i for i in safe if i["status"] not in ("resolved", "closed")],
            "resolved": [i for i in safe if i["status"] in ("resolved", "closed")],
        }

    @staticmethod
    def _safe_incident(incident: dict[str, Any]) -> dict[str, Any]:
        """Whitelist tenant-safe incident fields. NEVER expose internal_notes,
        root_cause, affected_tenants, affected_services, or owner ids."""
        return {
            "incident_id": incident.get("incident_id"),
            "title": incident.get("title"),
            "status": incident.get("status"),
            "severity": incident.get("severity"),
            "customer_impact": incident.get("customer_impact"),
            "started_at": incident.get("started_at"),
            "resolved_at": incident.get("resolved_at"),
            "updated_at": incident.get("updated_at"),
        }

    async def internal_summary(self) -> dict[str, Any]:
        """Cross-tenant impact rollup for Kyber operators."""
        incidents = await incident_service.list()
        tenant_ids = sorted({t for inc in incidents for t in (inc.get("affected_tenants") or [])})
        per_tenant = [await self.compute(tid) for tid in tenant_ids]
        return {
            "impacted_tenant_count": len(tenant_ids),
            "tenants": per_tenant,
            "generated_at": now_iso(),
        }


tenant_impact = TenantImpactAnalyzer()
