"""Per-provider comms coverage scoring (ADR-C11).

Honest, evidence-grounded coverage for the communications cohort. For every
registered comms connector this reports what Aether has actually observed —
identity mappings, active suppressions — next to the provider's *declared*
capabilities and readiness. Coverage is never fabricated: zero observations is
reported as zero, an un-resolvable identity stays provisional, and a provider
that cannot observe a dimension simply does not claim it.

Surface: ``GET /v1/comms/coverage`` (tenant) / ``GET /v1/comms/admin/coverage``
(operator aggregate). The certification matrix owns readiness; this module owns
observation coverage.
"""

from __future__ import annotations

from typing import Any, Optional

from services.comms.entitlements import is_comms_connector

_IDENTITY_RESOLVED = "resolved"
_IDENTITY_PROVISIONAL = "provisional"


def comms_providers() -> list[str]:
    """Registered comms connector types (provider-neutral, manifest-driven)."""
    from services.integrations.connectors.registry import CONNECTORS

    return sorted(
        ctype for ctype in CONNECTORS if is_comms_connector(ctype)
    )


def _provider_capabilities(provider: str) -> dict[str, Any]:
    """Declared connector surface (descriptor) — never fabricated."""
    try:
        from services.integrations.connectors.registry import CONNECTORS

        connector = CONNECTORS.get(provider)
        if connector is None:
            return {}
        desc = connector.descriptor()
        return {
            "supports_webhook": bool(desc.supports_webhook),
            "supports_pull": bool(desc.supports_pull),
            "supports_reconciliation": bool(desc.supports_reconciliation),
            "implementation_status": str(desc.implementation_status.value),
            "signature_scheme": getattr(connector, "signature_scheme", None),
            "required_credentials": tuple(getattr(connector, "required_credentials", ()) or ()),
        }
    except Exception:  # pragma: no cover - registry may be partial in local
        return {}


async def _identity_coverage(tenant_id: str, provider: str) -> dict[str, Any]:
    """Identity bridge observations per provider, grounded in the store."""
    from services.comms.identity_bridge import ProviderIdentityRepository

    repo = ProviderIdentityRepository()
    observed = await repo.count({"tenant_id": tenant_id, "provider": provider})
    resolved = await repo.count(
        {"tenant_id": tenant_id, "provider": provider,
         "resolution_status": _IDENTITY_RESOLVED}
    )
    provisional = await repo.count(
        {"tenant_id": tenant_id, "provider": provider,
         "resolution_status": _IDENTITY_PROVISIONAL}
    )
    return {
        "identities_observed": observed,
        "identities_resolved": resolved,
        "identities_provisional": provisional,
        "identity_resolution_rate": round(resolved / observed, 4) if observed else None,
    }


async def _suppression_coverage(tenant_id: str, provider: str) -> dict[str, int]:
    """Active suppressions recorded for the provider (reconciliation read)."""
    from services.comms.repository import CommunicationSuppressionRepository

    repo = CommunicationSuppressionRepository()
    active = await repo.list_active_for_tenant(tenant_id, provider=provider, limit=1000)
    return {"active_suppressions": len(active)}


async def provider_coverage(tenant_id: str, provider: str) -> Optional[dict[str, Any]]:
    """Coverage for a single provider, or ``None`` when it is not a comms provider."""
    if not is_comms_connector(provider):
        return None
    entry: dict[str, Any] = {"provider": provider, "capabilities": _provider_capabilities(provider)}
    entry.update(await _identity_coverage(tenant_id, provider))
    entry.update(await _suppression_coverage(tenant_id, provider))
    return entry


async def comms_coverage_report(
    tenant_id: str, *, provider: Optional[str] = None
) -> list[dict[str, Any]]:
    """Per-provider coverage for the comms cohort (optionally scoped to one)."""
    providers = [provider] if provider else comms_providers()
    report: list[dict[str, Any]] = []
    for p in providers:
        entry = await provider_coverage(tenant_id, p)
        if entry is not None:
            report.append(entry)
    return report
