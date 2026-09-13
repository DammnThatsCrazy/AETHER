"""The Kyber Tenant Mirror.

One invariant holds this package together:

    the tenant-visible result Aether returns for a tenant, query and contract
    version is *the same* result the Tenant Mirror returns.

Kyber may **add** operator diagnostics — data quality, lineage, policy, health,
recompute options. It may never recompute a tenant-visible value differently.
If it does, an operator investigating a tenant is debugging a different system
than the tenant runs, which is precisely the failure mode a mirror exists to
remove.

The mechanical consequence is that this package owns no calculations. Tenant
data is read through :mod:`services.kyber.graph.scoped_gateway`, timestamps are
normalised through :mod:`shared.temporal.instant`, measurement semantics come
from :mod:`shared.measurement.value_states`, and authorization is the single
Kyber access dependency. What this package *does* own is the response envelope,
the semantic parity digest, and the comparison that proves the invariant held.

Modules:
    ``contracts``  the envelope and the parity records
    ``parity``     canonicalisation, digesting, and located divergence
    ``service``    manifest resolution and rendering through the shared paths
    ``routes``     the operator-facing surface (mounted by the Kyber console)
"""
from __future__ import annotations

from .contracts import (
    DIAGNOSTIC_SECTIONS,
    MirrorEnvelope,
    OperatorDiagnostics,
    ParityComparison,
    ParityDigest,
    empty_diagnostics,
)
from .parity import (
    PRESENTATION_KEYS,
    canonical_payload,
    compare,
    digest_tenant_visible,
)
from .service import (
    SURFACE_VERTEX_TYPES,
    TenantMirrorService,
    get_gateway,
    reset_gateway,
    set_gateway,
    tenant_mirror_service,
)

__all__ = [
    "DIAGNOSTIC_SECTIONS",
    "PRESENTATION_KEYS",
    "SURFACE_VERTEX_TYPES",
    "MirrorEnvelope",
    "OperatorDiagnostics",
    "ParityComparison",
    "ParityDigest",
    "TenantMirrorService",
    "canonical_payload",
    "compare",
    "digest_tenant_visible",
    "empty_diagnostics",
    "get_gateway",
    "reset_gateway",
    "set_gateway",
    "tenant_mirror_service",
]
