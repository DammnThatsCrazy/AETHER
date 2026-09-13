"""Typed, versioned operator financial-health contract (Kyber ↔ backend).

One source of truth for the Kyber payment-rail operator surface, shared by the
backend routes and mirrored by the frontend zod schema
(``frontend/kyber/src/types/payment-rails.ts``). Every field is explicit so the
operator console can distinguish ``zero`` (a real 0 count) from ``unknown`` (a
value we cannot compute yet, encoded as ``null``) and from ``not_configured`` /
``disabled`` / ``degraded`` (encoded in ``status``). Aggregates never carry
tenant-private payment payloads — only adapter/config/reconciliation health and
sanitized counters.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0.0"

# Provider/health status vocabulary — the operator console renders each distinctly.
ProviderStatus = Literal[
    "healthy", "degraded", "error", "not_configured", "disabled", "unknown"
]


# ── Fleet-level ───────────────────────────────────────────────────────────────

class ProviderFleetRow(BaseModel):
    provider: str
    status: ProviderStatus
    enabled: bool
    configured_tenants: int
    webhook_verified_24h: int
    webhook_rejected_24h: int
    signature_failures_24h: int
    sessions_observed_24h: int
    sessions_completed_24h: int
    sessions_failed_24h: int
    sessions_pending: int
    sessions_stale: int
    sessions_unresolved: int
    reconciliation_matched_rate: Optional[float] = None  # None = unknown (no records)
    reconciliation_conflicts: int
    # Operational depth — None when not yet computable (never a misleading 0).
    polling_cursor_age_seconds: Optional[float] = None
    provider_probe_status: Optional[str] = None


class TenantFleetRow(BaseModel):
    tenant_id: str
    status: ProviderStatus
    providers_configured: int
    providers_degraded: int
    sessions_observed_24h: int
    sessions_unresolved: int
    reconciliation_conflicts: int


class FleetTotals(BaseModel):
    configured_tenants: int
    enabled_tenants: int
    providers_degraded: int
    sessions_observed_24h: int
    sessions_completed_24h: int
    sessions_failed_24h: int
    sessions_pending: int
    sessions_stale: int
    sessions_unresolved: int
    webhook_verified_24h: int
    webhook_rejected_24h: int
    signature_failures_24h: int
    reconciliation_matched_rate: Optional[float] = None
    reconciliation_conflicts: int
    # Delivery backlogs (from the durable receipt ledger).
    oldest_incomplete_receipt_age_seconds: Optional[float] = None
    canonical_backlog: int
    outbox_lag: Optional[int] = None  # None = not measured at fleet level
    repair_backlog: int
    dead_lettered: int
    # Worker liveness — None when unknown (no heartbeat observed this process).
    worker_heartbeat: Optional[bool] = None
    last_successful_worker_cycle: Optional[str] = None


class FleetHealthResponse(BaseModel):
    contract_version: str = CONTRACT_VERSION
    tenants_observed: int
    totals: FleetTotals
    providers: list[ProviderFleetRow]
    tenants: list[TenantFleetRow]


# ── Tenant-level ──────────────────────────────────────────────────────────────

class CredentialSlotState(BaseModel):
    slot_name: str
    required: bool
    configured: bool
    state: Optional[str] = None  # active|previous|pending|revoked|... ; None = unknown


class TenantProviderAdapter(BaseModel):
    status: str
    environment: Optional[str] = None
    webhook_configured: bool
    polling_configured: bool
    webhook_endpoint_registered: bool
    credential_slots: list[CredentialSlotState] = Field(default_factory=list)


class TenantProviderHealth(BaseModel):
    status: ProviderStatus
    sessions_observed_24h: int
    sessions_completed_24h: int
    sessions_failed_24h: int
    sessions_unresolved: int
    webhook_verified_24h: int
    webhook_rejected_24h: int
    reconciliation_matched_rate: Optional[float] = None
    reconciliation_conflicts: int
    last_event_at: Optional[str] = None
    last_poll_at: Optional[str] = None
    last_successful_poll_at: Optional[str] = None
    last_failed_poll_at: Optional[str] = None
    polling_cursor_age_seconds: Optional[float] = None
    provider_poll_health: Optional[str] = None
    connection_probe_result: Optional[str] = None


class TenantProviderDiagnostics(BaseModel):
    provider: str
    adapter: TenantProviderAdapter
    health: TenantProviderHealth


class TenantBacklogs(BaseModel):
    receipt_backlog: int
    canonical_backlog: int
    outbox_backlog: Optional[int] = None
    repair_backlog: int
    dead_lettered: int
    oldest_incomplete_receipt_age_seconds: Optional[float] = None


class TenantDiagnosticsResponse(BaseModel):
    contract_version: str = CONTRACT_VERSION
    tenant_id: str
    providers: list[TenantProviderDiagnostics]
    backlogs: TenantBacklogs
    recent_audit: list[dict[str, Any]] = Field(default_factory=list)
    recent_repair_outcomes: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "CONTRACT_VERSION",
    "ProviderStatus",
    "ProviderFleetRow",
    "TenantFleetRow",
    "FleetTotals",
    "FleetHealthResponse",
    "CredentialSlotState",
    "TenantProviderAdapter",
    "TenantProviderHealth",
    "TenantProviderDiagnostics",
    "TenantBacklogs",
    "TenantDiagnosticsResponse",
]
