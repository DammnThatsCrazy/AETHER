"""Reliability, SRE, Incident Response & Operational Resilience.

Internal reliability command center for Olympus Labs (Kyber) plus tenant-safe
system status for Aether tenants. Built additively on existing health checks,
event bus, repositories, integration actions, audit exports, billing metering,
and Kyber admin systems.

This package never exposes cross-tenant data or internal infrastructure details
to tenants, and never weakens tenant isolation, governance, or security controls.
"""

from services.reliability.routes import admin_router, tenant_router

__all__ = ["admin_router", "tenant_router"]
