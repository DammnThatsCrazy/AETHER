"""Data Quality, Drift Detection & Graph Intelligence Reliability.

Tenant-facing data-quality views for Aether plus an internal intelligence-quality
command center for Olympus Labs (Kyber). Built additively on top of existing
signals (ingestion, identity resolution, graph mutation, Profile360,
recommendations, outcomes, playbooks) and the reliability + security/governance
layers.

This package never exposes cross-tenant data or raw tenant-private payloads to
other tenants, and never weakens tenant isolation, governance, or security
controls. Critical contamination signals escalate into the Security/Governance
audit ledger rather than being silently surfaced.
"""

from services.data_quality.routes import admin_router, tenant_router

__all__ = ["admin_router", "tenant_router"]
