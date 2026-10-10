"""Typed schema for the capability contract (GET /v1/capabilities).

Replaces the previously schema-less dict so the tenant-facing capability
contract has one validated shape that the frontends can mirror (Zod) and gate
navigation / route access against. Only non-secret, tenant-safe fields appear.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class EnforcementState(BaseModel):
    """Runtime route-policy enforcement posture for the active profile."""

    policy_enforcement: bool
    route_registry_enforced: bool
    kyber_operator_gate: bool


class ReleaseCapabilities(BaseModel):
    """Non-secret release surface: what the active deployment profile offers."""

    deployment_profile: str
    environment: str
    release_class: Optional[str] = None
    enforcement: EnforcementState
    enabled_route_prefixes: list[str] = []
    excluded_domains: list[str] = []


class ProviderCapability(BaseModel):
    id: str
    category: str
    status: str
    last_successful_sync: Optional[str] = None
    error_count: int = 0
    staleness_label: str = "stale"
    circuit_breaker: str = "closed"


class CapabilitiesResponse(BaseModel):
    """Tenant capability discovery envelope (pre ``@api_response`` wrapping)."""

    tenant_id: str
    release: ReleaseCapabilities
    profile_sub_resources: list[str]
    providers: list[ProviderCapability]
    consent_purposes_granted: list[str]
    consent_purposes_all: list[str]
    feature_flags: dict[str, bool]
    evaluated_at: str


class OperatorCapabilitiesResponse(BaseModel):
    """Kyber operator capability read — release posture, no tenant data."""

    release: ReleaseCapabilities
    feature_flags: dict[str, bool]
    extraction_defense_mode: Optional[str] = None
    evaluated_at: str
