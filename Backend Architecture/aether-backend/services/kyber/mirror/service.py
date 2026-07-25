"""Manifest resolution and rendering — the part of the mirror that reads.

This service owns no calculation. That is not a style preference, it is the
mechanism by which the mirror invariant holds: if Kyber derived a tenant-visible
number here, that number would be Kyber's, and an operator investigating a
tenant would be reading a second implementation of the tenant's product. So the
only tenant read in this module goes through
:mod:`services.kyber.graph.scoped_gateway`, and
``scripts/validate_tenant_mirror_parity.py`` freezes that with an AST import
scan — an import of a calculation module fails CI rather than quietly shipping.

Two refusals matter more than the happy path:

* an **unknown** surface is a 404, never an empty payload. "This surface does
  not exist" and "this tenant has nothing" look identical to an operator
  reading a blank screen, and only one of them means the tenant is fine.
* a **parity-exempt** surface is refused *with its manifest reason*. Opting a
  surface out of the mirror is a deliberate product decision recorded in
  ``scripts/generate_feature_surface_manifest.py``; repeating the reason at the
  point of refusal is what stops someone re-deciding it at 3am.

Coverage lives in :data:`SURFACE_VERTEX_TYPES`. Every parity-required manifest
surface must appear there, and nothing else may — a coverage map that silently
stops covering something is worse than none, so both directions are gated.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.measurement.value_states import ValueState

from .contracts import (
    DIAGNOSTIC_SECTIONS,
    MirrorEnvelope,
    OperatorDiagnostics,
    ParityComparison,
    now_iso,
)
from .parity import compare, digest_tenant_visible

logger = get_logger("aether.kyber.mirror")

#: Capability the mirror routes gate on. Note that the *gateway* additionally
#: requires ``kyber.graph.tenant.read``: reading a tenant is one authority, and
#: rendering it as the tenant sees it is another. The ``_READ_TENANT`` role
#: bundle grants both together.
MIRROR_CAPABILITY = "kyber.tenant.mirror.read"
MIRROR_MASKED_CAPABILITY = "kyber.tenant.mirror.read_masked"

#: Manifest, relative to the repository root. Resolved by walking up from this
#: file rather than by a fixed number of ``parents[...]`` hops, because the
#: backend lives under a directory with a space in its name and a hop count is
#: silently wrong the moment the tree is re-laid-out.
_MANIFEST_RELATIVE = Path("packages") / "shared" / "contracts" / "kyber-feature-surface-manifest.json"

#: Per-vertex-type page size. Well under the gateway's own budget so a surface
#: reading several types cannot monopolise a read.
SURFACE_READ_LIMIT = 200

#: Which vertex types in the tenant's own graph each parity-required Aether
#: surface reads. Grouped by product area, one entry per manifest ``feature_id``.
#:
#: These are the *inputs* to a surface, not its rendering: the mirror reads them
#: through the scoped gateway and renders nothing of its own. A wrong entry here
#: shows up as a parity divergence, which is exactly where it should show up —
#: the gate below proves the map is complete, not that a choice is right.
SURFACE_VERTEX_TYPES: dict[str, tuple[str, ...]] = {
    # People and identity
    "users": ("User",),
    "users-id": ("User",),
    "clusters-clusterId": ("IdentityCluster",),
    "graph": ("Entity", "IdentityCluster"),
    # Campaigns
    "campaigns": ("Campaign",),
    "campaigns-id": ("Campaign",),
    "campaign-intelligence": ("AdCampaign", "RetargetRecommendation"),
    "campaign-intelligence-registry": ("AdCampaign",),
    "campaign-intelligence-sources": ("ExternalData",),
    "campaign-intelligence-mapping-review": ("ExternalData", "AdCampaign"),
    "campaign-intelligence-quality": ("ExternalData",),
    "campaign-intelligence-campaigns-new": ("AdCampaign",),
    # Decisions and outcomes
    "noesis": ("Recommendation", "DecisionRecord", "OutcomeObservation"),
    "suggestions": ("Recommendation",),
    "value-review": ("DecisionRecord", "OutcomeObservation"),
    # Geography
    "geo": ("Location", "LocationSummary"),
    "geo-level-geoId": ("Location", "LocationSummary"),
    # Platform-facing tenant surfaces
    "system-status": ("Service",),
    "data-quality": ("ExternalData", "Entity"),
    "integrations": ("MCPConnection", "ExternalAgenticAccount"),
    "imports": ("ExternalData",),
    "imports-id": ("ExternalData",),
    "deployments": ("Agent", "Service"),
    "deployments-id": ("Agent", "Service"),
    "delivery": ("Fulfillment", "DeliveryActor"),
    # Rewards and payments
    "rewards": ("Payment", "PaymentReceipt"),
    "rewards-decisions": ("PolicyDecision", "DecisionRecord"),
    "rewards-approval-queue": ("ApprovalRequest", "ApprovalDecision"),
    "rewards-rails": ("PaymentRoute", "PaymentNetwork"),
    "rewards-campaigns-new": ("Campaign",),
    "payment-rails": ("PaymentRoute", "PaymentNetwork", "CardProgram"),
    # Agents
    "agent-access": ("Agent", "AgentPermissionSet", "Capability"),
    "ai-efficiency": ("Agent", "AgentPerformanceSnapshotObserved"),
    # Markets
    "stablecoins": ("StablecoinAsset", "StablecoinDeployment"),
    "stablecoins-assetId": ("StablecoinAsset", "StablecoinDeployment"),
    "derivatives": ("TradingAccount", "Instrument", "Market"),
    "derivatives-accounts-accountId": ("TradingAccount",),
    # Interoperability
    "interoperability": (
        "InteropProvider", "InteropGateway", "InteropPath", "InteropApplication",
    ),
    "interoperability-messages-messageId": ("InteropPath", "InteropApplication"),
}


# ── Gateway injection ────────────────────────────────────────────────────────
#
# Same shape as `scoped_gateway.set_store`/`reset_store`, on purpose: one
# injection idiom across the Kyber planes means a test that fakes one plane
# reads the same as a test that fakes another. There is deliberately no
# try/except around the import — an unimportable gateway is a broken build, and
# degrading it into "the mirror reads nothing" would report a healthy, empty
# tenant for an infrastructure fault.

_gateway: Any = None


def set_gateway(gateway: Any) -> None:
    """Install the scoped tenant gateway. The seam tests use to supply a fake."""
    global _gateway
    _gateway = gateway


def reset_gateway() -> None:
    """Forget the injected gateway so the next call resolves the real one."""
    global _gateway
    _gateway = None


def get_gateway() -> Any:
    """The scoped tenant graph gateway — the only sanctioned tenant read."""
    if _gateway is not None:
        return _gateway
    from ..graph.scoped_gateway import scoped_tenant_graph_gateway

    return scoped_tenant_graph_gateway


# ── Manifest ─────────────────────────────────────────────────────────────────


def _repository_root() -> Path:
    """Walk up until the feature-surface manifest is found."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / _MANIFEST_RELATIVE).is_file():
            return candidate
    raise FileNotFoundError(
        f"Kyber feature-surface manifest not found: no ancestor of {__file__} "
        f"contains {_MANIFEST_RELATIVE}"
    )


def load_manifest() -> dict[str, Any]:
    """Read the feature-surface manifest. A missing manifest is fatal.

    There is no fallback. The manifest is what says which surfaces owe parity;
    a mirror that ran without it would answer for surfaces nobody classified.
    """
    path = _repository_root() / _MANIFEST_RELATIVE
    return json.loads(path.read_text())


class TenantMirrorService:
    """Resolves a surface, reads it through the gateway, and attaches diagnostics.

    The manifest is read once and cached on the instance; it is generated
    content that only changes with a deploy. ``reload()`` exists for tests and
    for an operator confirming a manifest change landed.
    """

    def __init__(self, manifest: Optional[dict[str, Any]] = None) -> None:
        self._manifest = manifest
        self._by_feature: dict[str, dict[str, Any]] = {}
        self._by_route: dict[str, dict[str, Any]] = {}
        if manifest is not None:
            self._index(manifest)

    # ── Manifest access ──────────────────────────────────────────────────────

    def _index(self, manifest: dict[str, Any]) -> None:
        self._by_feature = {}
        self._by_route = {}
        for entry in manifest.get("surfaces", []):
            feature_id = str(entry.get("feature_id") or "")
            route = str(entry.get("aether_route") or "")
            if feature_id:
                self._by_feature[feature_id] = entry
            if route:
                self._by_route[route] = entry

    @property
    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            self._manifest = load_manifest()
            self._index(self._manifest)
        return self._manifest

    def reload(self) -> None:
        """Drop the cached manifest so the next access re-reads it."""
        self._manifest = None
        self._by_feature = {}
        self._by_route = {}

    @property
    def contract_version(self) -> str:
        """The manifest schema version — the contract the digest is bound to."""
        return str(self.manifest.get("schemaVersion") or "unknown")

    def parity_required_ids(self) -> tuple[str, ...]:
        """Every manifest surface that owes byte parity, in manifest order."""
        _ = self.manifest  # force the lazy load before reading the index
        return tuple(
            feature_id
            for feature_id, entry in self._by_feature.items()
            if entry.get("tenant_parity_required")
        )

    def resolve(self, surface: str) -> dict[str, Any]:
        """The manifest entry for a surface, by ``feature_id`` or Aether route.

        Raises:
            NotFoundError: The surface is not in the manifest at all.
            BadRequestError: The surface exists but is exempt from parity; the
                manifest's own exception reason is carried on the error so the
                refusal explains itself.
        """
        _ = self.manifest  # force the lazy load before reading the index
        key = str(surface or "").strip()
        entry = self._by_feature.get(key)
        if entry is None:
            route = key if key.startswith("/") else f"/{key}"
            entry = self._by_route.get(route)
        if entry is None:
            metrics.increment("kyber_mirror_refused_total", labels={"reason": "unknown_surface"})
            raise NotFoundError(
                "Tenant mirror surface",
                details={"surface": key, "known_surfaces": len(self._by_feature)},
            )
        if not entry.get("tenant_parity_required"):
            metrics.increment("kyber_mirror_refused_total", labels={"reason": "parity_exempt"})
            reason = entry.get("parity_exception_reason") or "no reason recorded in the manifest"
            raise BadRequestError(
                f"{entry.get('aether_route')} has no Tenant Mirror: {reason}",
                details={
                    "surface": entry.get("feature_id"),
                    "aether_route": entry.get("aether_route"),
                    "parity_exception_reason": entry.get("parity_exception_reason"),
                },
            )
        return entry

    def vertex_types(self, feature_id: str) -> tuple[str, ...]:
        """Which tenant vertex types a surface reads.

        A parity-required surface with no entry is a coverage hole, not an empty
        surface, so it refuses. ``scripts/validate_tenant_mirror_parity.py``
        catches the same condition in CI, before an operator ever hits it.
        """
        types = SURFACE_VERTEX_TYPES.get(feature_id)
        if not types:
            metrics.increment("kyber_mirror_refused_total", labels={"reason": "no_resolver"})
            raise NotFoundError(
                f"Tenant mirror resolver for surface {feature_id!r}",
                details={
                    "surface": feature_id,
                    "detail": (
                        "the manifest requires parity for this surface but "
                        "SURFACE_VERTEX_TYPES declares no vertex types for it"
                    ),
                },
            )
        return types

    # ── Rendering ────────────────────────────────────────────────────────────

    async def render(
        self,
        request: Any,
        *,
        tenant_id: str,
        surface: str,
    ) -> MirrorEnvelope:
        """The tenant-visible result for one surface, plus operator diagnostics.

        Every value in ``tenantVisible`` came out of the scoped gateway. Nothing
        is derived here — the diagnostics are assembled from what the gateway
        already reported about its own read, which is also why they cannot drift
        from it.
        """
        entry = self.resolve(surface)
        feature_id = str(entry["feature_id"])
        types = self.vertex_types(feature_id)
        gateway = get_gateway()

        entities: dict[str, list[Any]] = {}
        counts: dict[str, int] = {}
        reads: dict[str, dict[str, Any]] = {}
        rendered_tenant: Optional[str] = None
        truncated = False

        for vertex_type in types:
            result = await gateway.query(
                request,
                tenant_id=tenant_id,
                vertex_type=vertex_type,
                limit=SURFACE_READ_LIMIT,
            )
            visible = dict(result.get("tenantVisible") or {})
            diagnostics = dict(result.get("operatorDiagnostics") or {})
            reads[vertex_type] = diagnostics
            entities[vertex_type] = list(visible.get("vertices") or [])
            counts[vertex_type] = len(entities[vertex_type])
            truncated = truncated or bool(visible.get("truncated"))
            if rendered_tenant is None:
                rendered_tenant = visible.get("tenant_id")

        # `entity_counts` and `entity_count` are DELIBERATELY not here. They are
        # `len()` and `sum()` — computed by this package, not returned by the
        # gateway — and under truncation they count what this read *saw*, not
        # what the tenant has. Placing them in `tenantVisible` put them inside
        # the parity digest, which meant two states differing only past the read
        # limit digested identically, and a `check_parity` divergence at
        # `entity_count` blamed Aether for a number Aether never produced. A
        # value the mirror derives is by definition not a tenant-visible value,
        # so it belongs in the diagnostics beside the read that produced it.
        tenant_visible: dict[str, Any] = {
            "surface": feature_id,
            "aether_route": entry.get("aether_route"),
            "tenant_id": rendered_tenant if rendered_tenant is not None else tenant_id,
            "vertex_types": list(types),
            "entities": entities,
            "truncated": truncated,
        }

        disclosure = _first(reads, "granted_disclosure")
        masked = bool(_first(reads, "identifiers_masked"))
        diagnostics = self._diagnostics(
            entry, types=types, reads=reads, truncated=truncated, read_counts=counts
        )

        metrics.increment(
            "kyber_mirror_render_total",
            labels={"surface": feature_id, "truncated": str(truncated).lower()},
        )
        return MirrorEnvelope(
            surface_id=feature_id,
            aether_route=entry.get("aether_route"),
            tenant_id=str(tenant_id),
            contract_version=self.contract_version,
            generated_at=now_iso(),
            disclosure=str(disclosure) if disclosure is not None else None,
            # A masked rendering redacts identifiers by design, so it is not
            # the tenant's own result and must never be digested as one. A
            # TRUNCATED rendering is not the tenant's own result either: it is a
            # prefix. Digesting a prefix and comparing it against Aether's full
            # answer manufactures a divergence, and — worse — two different
            # tenant states that agree on the first SURFACE_READ_LIMIT rows
            # digest the same, so `customer_visible_parity` would report parity
            # across a change it never saw.
            parity_comparable=not masked and not truncated,
            tenantVisible=tenant_visible,
            operatorDiagnostics=diagnostics,
        )

    async def check_parity(
        self,
        request: Any,
        *,
        tenant_id: str,
        surface: str,
        aether_payload: Any,
    ) -> ParityComparison:
        """Compare Aether's tenant-visible payload against the mirror's.

        The Aether payload is supplied by the caller rather than fetched here.
        Fetching it would mean Kyber holding tenant credentials and calling the
        tenant's own API, which is a far larger authority than reading one
        tenant's graph under a purpose-bound scope — and it would make the
        comparison depend on Kyber's client rather than on the tenant's.
        """
        envelope = await self.render(request, tenant_id=tenant_id, surface=surface)
        if not envelope.parity_comparable:
            raise BadRequestError(
                "This rendering is masked and is not comparable against Aether",
                details={
                    "surface": envelope.surface_id,
                    "disclosure": envelope.disclosure,
                    "detail": (
                        "a masked mirror redacts identifiers by design; comparing it "
                        "would report redactions as divergence"
                    ),
                },
            )
        comparison = compare(
            aether_payload,
            envelope.tenantVisible,
            contract_version=envelope.contract_version,
        )
        metrics.increment(
            "kyber_mirror_parity_total",
            labels={"surface": envelope.surface_id, "matched": str(comparison.matched).lower()},
        )
        if not comparison.matched:
            logger.warning(
                f"kyber: tenant mirror parity mismatch surface={envelope.surface_id} "
                f"divergences={comparison.divergence_count}"
            )
        return comparison

    def digest(self, envelope: MirrorEnvelope) -> Any:
        """The parity digest of one rendered envelope's tenant-visible payload."""
        return digest_tenant_visible(
            envelope.tenantVisible, contract_version=envelope.contract_version
        )

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def _diagnostics(
        self,
        entry: dict[str, Any],
        *,
        types: tuple[str, ...],
        reads: dict[str, dict[str, Any]],
        truncated: bool,
        read_counts: Optional[dict[str, int]] = None,
    ) -> OperatorDiagnostics:
        """Assemble the five augmentation sections from the gateway's own report.

        Nothing here is recomputed from the tenant's data. Every field is either
        copied from a gateway diagnostic block or is a fact about the manifest,
        which is what makes these additive by construction.
        """
        missing: list[str] = []
        for vertex_type, block in reads.items():
            for item in block.get("missing_inputs") or ():
                missing.append(f"{vertex_type}:{item}")
        complete = not truncated and not missing

        # The same rule the graph plane follows: an incomplete read is never
        # reported as healthy, no reads at all is `no_data`, and a read whose
        # gateway reported nothing about itself is `unknown` — never healthy.
        if not reads:
            health_state = "no_data"
        elif not any(reads.values()):
            health_state = "unknown"
        elif not complete:
            health_state = "degraded"
        else:
            health_state = "healthy"

        value_state = (
            ValueState.OBSERVED.value if complete else ValueState.MISSING_INPUTS.value
        )

        return OperatorDiagnostics(
            quality={
                "value_state": value_state,
                "complete": complete,
                "truncated": truncated,
                "missing_inputs": sorted(set(missing)),
                "reads_issued": len(reads),
                # Rows this read SAW, per vertex type, and their total. Named
                # "read" rather than "entity" on purpose: under truncation they
                # are a lower bound on what the tenant has, not a count of it.
                # They live here rather than in `tenantVisible` because the
                # mirror derived them, and a value the mirror derives is not a
                # tenant-visible value — see `render`.
                "rows_read": dict(read_counts or {}),
                "rows_read_total": sum((read_counts or {}).values()),
                "rows_read_is_lower_bound": truncated,
                "exposure_known": all(
                    bool(block.get("exposure_known")) for block in reads.values()
                ) if reads else False,
            },
            lineage={
                "source": "services.kyber.graph.scoped_gateway",
                "vertex_types": list(types),
                "scope_id": _first(reads, "scope_id"),
                "purpose": _first(reads, "purpose"),
                "evidence_reference_count": sum(
                    int(block.get("evidence_reference_count") or 0) for block in reads.values()
                ),
                "evidence_disclosure_gated": any(
                    bool(block.get("evidence_disclosure_gated")) for block in reads.values()
                ),
            },
            policy={
                "mirror_capability": entry.get("backend_capability") or MIRROR_CAPABILITY,
                "gateway_capability": _first(reads, "capability"),
                "manifest_minimum_disclosure": entry.get("minimum_disclosure"),
                "granted_disclosure": _first(reads, "granted_disclosure"),
                "identifiers_masked": bool(_first(reads, "identifiers_masked")),
                "tenant_scope": "required",
                "tenant_parity_required": True,
            },
            health={
                "state": health_state,
                "surface": entry.get("feature_id"),
                "reads": {
                    vertex_type: {
                        "result_count": block.get("result_count"),
                        "truncated": block.get("truncated"),
                        "budget": block.get("budget"),
                    }
                    for vertex_type, block in reads.items()
                },
                "computed_at": now_iso(),
            },
            recomputeOptions=_recompute_options(entry),
        )


def _first(reads: dict[str, dict[str, Any]], key: str) -> Any:
    """The first non-``None`` value for ``key`` across the gateway's blocks.

    Every block in one render came from one authorization, so scope, purpose
    and disclosure are identical across them; taking the first is a read, not a
    reconciliation.
    """
    for block in reads.values():
        value = block.get(key)
        if value is not None:
            return value
    return None


def _recompute_options(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """What an operator could ask to be recomputed, and where.

    Declarations only. A read route never runs a recompute — that is the
    command plane's action class, and offering it from here would let a D3 read
    capability trigger a class-3 action. Each option therefore names the plane
    that owns it and says plainly that it is not available from this route.
    """
    if "recomputeOptions" not in DIAGNOSTIC_SECTIONS:  # pragma: no cover - guarded by CI
        return []
    return [
        {
            "option_id": "recompute_surface",
            "label": f"Recompute {entry.get('feature_id')} for this tenant",
            "capability": "kyber.command.recompute",
            "offered_by": "kyber command plane",
            "available_here": False,
            "reason": "the Tenant Mirror is a read surface; recompute is a class-3 action",
        },
        {
            "option_id": "rebuild_projection",
            "label": f"Rebuild the projections behind {entry.get('feature_id')}",
            "capability": "kyber.command.rebuild",
            "offered_by": "kyber command plane",
            "available_here": False,
            "reason": "the Tenant Mirror is a read surface; rebuild is a class-3 action",
        },
    ]


#: Process-wide service. Stateless apart from the cached manifest.
tenant_mirror_service = TenantMirrorService()


__all__ = [
    "MIRROR_CAPABILITY",
    "MIRROR_MASKED_CAPABILITY",
    "SURFACE_READ_LIMIT",
    "SURFACE_VERTEX_TYPES",
    "TenantMirrorService",
    "get_gateway",
    "load_manifest",
    "reset_gateway",
    "set_gateway",
    "tenant_mirror_service",
]
