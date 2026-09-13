"""
Aether Graph — Vertex/Edge Schema Documentation (L3b+).

Documents owner, tenant isolation, provenance, audit requirements, DSR
treatment, and Kyber visualization binding for:
  - every commerce vertex/edge type added by the Agentic Commerce control
    plane (COMMERCE_* lists), and
  - the Financial Normalization reference layer (WP6a) — the global
    canonical-asset/chain/deployment/fiat reference vertices and their
    non-actor reference edges (REFERENCE_* lists). Reference vertices are
    GLOBAL (tenant_scoped=False), mirroring how global/domain vertices such
    as Facilitator and StablecoinAsset declare tenant isolation today.

This module is documentation-as-code: it is imported by tests and
`validate_contracts.py` to assert completeness.  Nothing here creates
graph objects — `shared/graph/graph.py` holds the enum constants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class VertexSchema:
    vertex_type: str
    owner_service: str
    tenant_scoped: bool        # True → key is {tenant_id}:{vertex_id}
    provenance_event: str      # which domain event creates this vertex
    audit_required: bool
    dsr_action: str            # "pseudonymize" | "retain" | "N/A"
    source_of_truth: str       # the method/service that is canonical writer
    kyber_surfaces: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EdgeSchema:
    edge_type: str
    from_type: str
    to_type: str
    properties: list[str]      # key properties carried on the edge
    creation_path: str         # the service/method that writes this edge


# ── Commerce Vertex Schemas ────────────────────────────────────────────────

COMMERCE_VERTEX_SCHEMAS: list[VertexSchema] = [
    VertexSchema(
        vertex_type="PaymentRequirement",
        owner_service="control_plane",
        tenant_scoped=True,
        provenance_event="aether.commerce.challenge.issued",
        audit_required=True,
        dsr_action="pseudonymize",
        source_of_truth="control_plane.issue_challenge",
        kyber_surfaces=["Noesis", "Review", "Mission"],
    ),
    VertexSchema(
        vertex_type="PaymentAuthorization",
        owner_service="control_plane",
        tenant_scoped=True,
        provenance_event="aether.commerce.approval.approved",
        audit_required=True,
        dsr_action="pseudonymize",
        source_of_truth="approvals.apply_decision",
        kyber_surfaces=["Noesis", "Review"],
    ),
    VertexSchema(
        vertex_type="PaymentReceipt",
        owner_service="verification",
        tenant_scoped=True,
        provenance_event="aether.commerce.verification.succeeded",
        audit_required=True,
        dsr_action="retain",  # financial record obligation
        source_of_truth="verification.verify",
        kyber_surfaces=["Diagnostics", "Entities"],
    ),
    VertexSchema(
        vertex_type="Settlement",
        owner_service="settlement",
        tenant_scoped=True,
        provenance_event="aether.commerce.settlement.completed",
        audit_required=True,
        dsr_action="retain",  # financial record obligation
        source_of_truth="settlement.fsm_transition",
        kyber_surfaces=["Diagnostics", "Noesis", "Entities"],
    ),
    VertexSchema(
        vertex_type="Entitlement",
        owner_service="entitlements",
        tenant_scoped=True,
        provenance_event="aether.commerce.entitlement.granted",
        audit_required=True,
        dsr_action="pseudonymize",
        source_of_truth="entitlements.mint",
        kyber_surfaces=["Entities", "Noesis"],
    ),
    VertexSchema(
        vertex_type="AccessGrant",
        owner_service="control_plane",
        tenant_scoped=True,
        provenance_event="aether.commerce.access.granted",
        audit_required=True,
        dsr_action="pseudonymize",
        source_of_truth="control_plane.grant_access",
        kyber_surfaces=["Entities"],
    ),
    VertexSchema(
        vertex_type="Fulfillment",
        owner_service="control_plane",
        tenant_scoped=True,
        provenance_event="aether.commerce.access.granted",
        audit_required=True,
        dsr_action="pseudonymize",
        source_of_truth="control_plane.record_fulfillment",
        kyber_surfaces=["Entities"],
    ),
    VertexSchema(
        vertex_type="ApprovalRequest",
        owner_service="approvals",
        tenant_scoped=True,
        provenance_event="aether.commerce.approval.requested",
        audit_required=True,
        dsr_action="pseudonymize",
        source_of_truth="approvals.request",
        kyber_surfaces=["Noesis", "Review", "Command"],
    ),
    VertexSchema(
        vertex_type="ApprovalDecision",
        owner_service="approvals",
        tenant_scoped=True,
        provenance_event="aether.commerce.approval.approved",
        audit_required=True,
        dsr_action="pseudonymize",
        source_of_truth="approvals.decide",
        kyber_surfaces=["Review", "Entities"],
    ),
    VertexSchema(
        vertex_type="PolicyDecision",
        owner_service="policies",
        tenant_scoped=True,
        provenance_event="aether.commerce.policy.denied",
        audit_required=True,
        dsr_action="retain",
        source_of_truth="PolicyEngine.evaluate",
        kyber_surfaces=["Review", "Diagnostics", "Entities"],
    ),
    VertexSchema(
        vertex_type="Facilitator",
        owner_service="facilitators",
        tenant_scoped=False,  # global + tenant allow-list
        provenance_event="admin.facilitator.registered",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="facilitators_registry",
        kyber_surfaces=["Command", "Diagnostics"],
    ),
    VertexSchema(
        vertex_type="StablecoinAsset",
        owner_service="facilitators",
        tenant_scoped=False,  # global
        provenance_event="admin.asset.registered",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="asset_registry",
        kyber_surfaces=["Command"],
    ),
    VertexSchema(
        vertex_type="PricePolicy",
        owner_service="pricing",
        tenant_scoped=True,
        provenance_event="admin.policy.created",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="policies_repo",
        kyber_surfaces=["Entities"],
    ),
    VertexSchema(
        vertex_type="BudgetPolicy",
        owner_service="policies",
        tenant_scoped=True,
        provenance_event="admin.policy.created",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="policies_repo",
        kyber_surfaces=["Entities"],
    ),
    VertexSchema(
        vertex_type="Treasury",
        owner_service="commerce",
        tenant_scoped=True,
        provenance_event="admin.treasury.configured",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="treasury_repo",
        kyber_surfaces=["Entities", "Mission"],
    ),
    VertexSchema(
        vertex_type="ServicePlan",
        owner_service="commerce",
        tenant_scoped=True,
        provenance_event="admin.plan.created",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="plans_repo",
        kyber_surfaces=["Entities"],
    ),
    VertexSchema(
        vertex_type="PaymentRoute",
        owner_service="facilitators",
        tenant_scoped=True,
        provenance_event="aether.commerce.facilitator.route_selected",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="route_selection",
        kyber_surfaces=["Diagnostics"],
    ),
    VertexSchema(
        vertex_type="EconomicCluster",
        owner_service="analytics",
        tenant_scoped=True,
        provenance_event="analytics.cluster.computed",
        audit_required=False,
        dsr_action="pseudonymize",
        source_of_truth="analytics_projection",
        kyber_surfaces=["Entities", "Diagnostics"],
    ),
]


# ── Commerce Edge Schemas ──────────────────────────────────────────────────

COMMERCE_EDGE_SCHEMAS: list[EdgeSchema] = [
    EdgeSchema(
        edge_type="REQUIRES_PAYMENT",
        from_type="ProtectedResource",
        to_type="PaymentRequirement",
        properties=["amount_usd", "chain", "asset"],
        creation_path="control_plane.issue_challenge",
    ),
    EdgeSchema(
        edge_type="OFFERS_PAYMENT_OPTION",
        from_type="PaymentRequirement",
        to_type="StablecoinAsset",
        properties=["preferred", "priority"],
        creation_path="price_policy_resolution",
    ),
    EdgeSchema(
        edge_type="AUTHORIZED_BY",
        from_type="PaymentRequirement",
        to_type="PaymentAuthorization",
        properties=["decided_at"],
        creation_path="approvals.apply_decision",
    ),
    EdgeSchema(
        edge_type="VERIFIED_BY",
        from_type="PaymentAuthorization",
        to_type="Facilitator",
        properties=["tx_hash", "verified_at"],
        creation_path="verification.verify",
    ),
    EdgeSchema(
        edge_type="SETTLED_BY",
        from_type="PaymentReceipt",
        to_type="Settlement",
        properties=["state", "retries"],
        creation_path="settlement.fsm_transition",
    ),
    EdgeSchema(
        edge_type="GRANTS_ACCESS_TO",
        from_type="Entitlement",
        to_type="ProtectedResource",
        properties=["scope", "expires_at"],
        creation_path="entitlements.mint",
    ),
    EdgeSchema(
        edge_type="FULFILLED_BY",
        from_type="AccessGrant",
        to_type="Fulfillment",
        properties=["latency_ms", "status"],
        creation_path="control_plane.record_fulfillment",
    ),
    EdgeSchema(
        edge_type="FUNDED_FROM_TREASURY",
        from_type="PaymentAuthorization",
        to_type="Treasury",
        properties=["amount"],
        creation_path="treasury_deduction",
    ),
    EdgeSchema(
        edge_type="PRICES_IN",
        from_type="ServicePlan",
        to_type="StablecoinAsset",
        properties=["unit_price"],
        creation_path="plan_config",
    ),
    EdgeSchema(
        edge_type="ACCEPTS_ASSET",
        from_type="ProtectedResource",
        to_type="StablecoinAsset",
        properties=["priority"],
        creation_path="resource_policy",
    ),
    EdgeSchema(
        edge_type="PREFERS_NETWORK",
        from_type="Treasury",
        to_type="Chain",
        properties=["priority"],
        creation_path="treasury_config",
    ),
    EdgeSchema(
        edge_type="CONSTRAINED_BY",
        from_type="Agent",
        to_type="BudgetPolicy",
        properties=["role"],
        creation_path="policy_binding",
    ),
    EdgeSchema(
        edge_type="SUBSCRIBES_TO",
        from_type="User",
        to_type="ServicePlan",
        properties=["started_at", "expires_at"],
        creation_path="subscription",
    ),
    EdgeSchema(
        edge_type="REUSES_ENTITLEMENT",
        from_type="Agent",
        to_type="Entitlement",
        properties=["count", "last_used"],
        creation_path="entitlements.reuse",
    ),
    EdgeSchema(
        edge_type="RETRIED_AS",
        from_type="Settlement",
        to_type="Settlement",
        properties=["reason", "attempt"],
        creation_path="settlement.retry",
    ),
    EdgeSchema(
        edge_type="ESCALATES_PAYMENT_TO",
        from_type="ApprovalRequest",
        to_type="User",
        properties=["reason"],
        creation_path="approvals.escalate",
    ),
    EdgeSchema(
        edge_type="GUARDED_BY_POLICY",
        from_type="ProtectedResource",
        to_type="PricePolicy",
        properties=["active"],
        creation_path="policy_binding",
    ),
    EdgeSchema(
        edge_type="ROUTES_VIA",
        from_type="PaymentAuthorization",
        to_type="PaymentRoute",
        properties=["facilitator_id"],
        creation_path="route_selection",
    ),
    EdgeSchema(
        edge_type="APPROVED_BY",
        from_type="ApprovalDecision",
        to_type="User",
        properties=["role"],
        creation_path="approvals.decide",
    ),
    EdgeSchema(
        edge_type="REJECTED_BY",
        from_type="ApprovalDecision",
        to_type="User",
        properties=["reason"],
        creation_path="approvals.decide",
    ),
    EdgeSchema(
        edge_type="REQUESTS_APPROVAL_FROM",
        from_type="ApprovalRequest",
        to_type="User",
        properties=["priority"],
        creation_path="approvals.assign",
    ),
    EdgeSchema(
        edge_type="GOVERNED_BY_POLICY",
        from_type="Tenant",
        to_type="PolicyDecision",
        properties=["context"],
        creation_path="PolicyEngine.evaluate",
    ),
]


# ── Financial Normalization — Reference Vertex Schemas (WP6a) ──────────────
# Reference vertices are canonical financial-registry data (asset / deployment /
# chain / fiat currency / issuer / price provider / venue / bridge). They are
# GLOBAL — tenant_scoped=False (matching Facilitator / StablecoinAsset) — and
# non-actor: tenant-owned records reference them by id, but the reference layer
# itself is not tenant-mutable (FINANCIAL_NORMALIZATION.md §9).

REFERENCE_VERTEX_SCHEMAS: list[VertexSchema] = [
    VertexSchema(
        vertex_type="Asset",
        owner_service="assets",
        tenant_scoped=False,  # global canonical registry row (fiat/crypto/stablecoin/token)
        provenance_event="registry.asset.seeded",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="asset_registry",
        kyber_surfaces=["Entities", "Noesis"],
    ),
    VertexSchema(
        vertex_type="AssetDeployment",
        owner_service="assets",
        tenant_scoped=False,  # global registry row: deploy:<asset_id>@<chain>:<contract>
        provenance_event="registry.deployment.seeded",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="deployment_registry",
        kyber_surfaces=["Entities", "Noesis"],
    ),
    VertexSchema(
        vertex_type="Chain",
        owner_service="assets",
        tenant_scoped=False,  # global registry row (CAIP-2 chain namespace)
        provenance_event="registry.chain.seeded",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="chain_registry",
        kyber_surfaces=["Entities", "Noesis"],
    ),
    VertexSchema(
        vertex_type="FiatCurrency",
        owner_service="assets",
        tenant_scoped=False,  # global ISO-4217 reference data (FIAT_REFERENCE_SEED)
        provenance_event="registry.fiat.seeded",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="fiat_reference",
        kyber_surfaces=["Entities", "Noesis"],
    ),
    VertexSchema(
        vertex_type="Issuer",
        owner_service="assets",
        tenant_scoped=False,  # global canonical issuer reference (stablecoin/token project)
        provenance_event="registry.issuer.seeded",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="asset_registry",
        kyber_surfaces=["Entities", "Noesis"],
    ),
    VertexSchema(
        vertex_type="PriceProvider",
        owner_service="valuation",
        tenant_scoped=False,  # global price-feed / oracle provider reference
        provenance_event="registry.price_provider.seeded",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="price_provider_registry",
        kyber_surfaces=["Entities", "Noesis"],
    ),
    VertexSchema(
        vertex_type="Venue",
        owner_service="assets",
        tenant_scoped=False,  # global trading/listing venue reference
        provenance_event="registry.venue.seeded",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="venue_registry",
        kyber_surfaces=["Entities", "Noesis"],
    ),
    VertexSchema(
        vertex_type="Bridge",
        owner_service="assets",
        tenant_scoped=False,  # global bridge operator/router reference
        provenance_event="registry.bridge.seeded",
        audit_required=True,
        dsr_action="N/A",
        source_of_truth="bridge_registry",
        kyber_surfaces=["Entities", "Noesis"],
    ),
]


# ── Financial Normalization — Reference Edge Schemas (WP6a) ────────────────
# Reference edges connect a domain/tenant subject OR another reference vertex
# to the global reference vertices above. They classify as EXCLUDED in
# relationship_layers.py (non-actor reference layer) and are written by the
# versioned registry → graph projectors. Edges whose enum literal pre-existed
# in other domains (DEPLOYED_ON_CHAIN, ISSUED_BY, PEGGED_TO, PRICED_BY,
# VALUED_AT, RECONCILED_WITH) are registered here for their canonical
# reference-layer usage; the graph carries one literal per edge type.

REFERENCE_EDGE_SCHEMAS: list[EdgeSchema] = [
    EdgeSchema(
        edge_type="DENOMINATED_IN",
        from_type="Instrument",
        to_type="FiatCurrency",
        properties=["iso_code"],
        creation_path="financial_normalization.denomination_projection",
    ),
    EdgeSchema(
        edge_type="PAID_WITH",
        from_type="Payment",
        to_type="Asset",
        properties=["economic_role", "amount"],
        creation_path="financial_normalization.payment_projection",
    ),
    EdgeSchema(
        edge_type="SETTLED_IN",
        from_type="Settlement",
        to_type="AssetDeployment",
        properties=["amount", "settled_at"],
        creation_path="financial_normalization.settlement_projection",
    ),
    EdgeSchema(
        edge_type="CHARGED_IN",
        from_type="Payment",
        to_type="Asset",
        properties=["economic_role", "amount"],
        creation_path="financial_normalization.charge_projection",
    ),
    EdgeSchema(
        edge_type="ASSESSED_IN",
        from_type="FinancialAccount",
        to_type="FiatCurrency",
        properties=["amount", "assessed_at"],
        creation_path="financial_normalization.assessment_projection",
    ),
    EdgeSchema(
        edge_type="DEPLOYED_ON_CHAIN",
        from_type="AssetDeployment",
        to_type="Chain",
        properties=["contract_or_mint", "decimals", "canonical_vs_bridged", "deployment_status"],
        creation_path="assets.deployment_projection",
    ),
    EdgeSchema(
        edge_type="ISSUED_BY",
        from_type="Asset",
        to_type="Issuer",
        properties=["issuer_role"],
        creation_path="assets.registry",
    ),
    EdgeSchema(
        edge_type="PEGGED_TO",
        from_type="Asset",
        to_type="Asset",
        properties=["peg_basis", "target_ratio"],
        creation_path="assets.peg_registry",
    ),
    EdgeSchema(
        edge_type="WRAPS",
        from_type="AssetDeployment",
        to_type="AssetDeployment",
        properties=["wrapped_contract", "canonical_vs_bridged"],
        creation_path="assets.deployment_projection",
    ),
    EdgeSchema(
        edge_type="BRIDGED_FROM",
        from_type="AssetDeployment",
        to_type="AssetDeployment",
        properties=["bridge_id", "origin_deployment_id"],
        creation_path="assets.bridge_projection",
    ),
    EdgeSchema(
        edge_type="PRICED_BY",
        from_type="Asset",
        to_type="PriceProvider",
        properties=["quote_asset_id", "freshness_window_seconds"],
        creation_path="valuation.price_projection",
    ),
    EdgeSchema(
        edge_type="VALUED_IN",
        from_type="Payment",
        to_type="FiatCurrency",
        properties=["native_currency", "native_amount"],
        creation_path="valuation.snapshot_projection",
    ),
    EdgeSchema(
        edge_type="VALUED_AT",
        from_type="AssetDeployment",
        to_type="Asset",
        properties=["reporting_asset_id", "valuation_basis", "valuation_method", "price_status"],
        creation_path="valuation.snapshot_projection",
    ),
    EdgeSchema(
        edge_type="DERIVED_FROM",
        from_type="AssetDeployment",
        to_type="AssetDeployment",
        properties=["derivation", "source_refs"],
        creation_path="financial_normalization.derivation_projection",
    ),
    EdgeSchema(
        edge_type="RECONCILED_WITH",
        from_type="AssetDeployment",
        to_type="AssetDeployment",
        properties=["reconciliation_state", "observed_balance", "expected_balance"],
        creation_path="assets.reconciliation_projection",
    ),
    EdgeSchema(
        edge_type="REVERSES",
        from_type="Payment",
        to_type="Payment",
        properties=["economic_role", "reason"],
        creation_path="financial_normalization.reversal_projection",
    ),
    EdgeSchema(
        edge_type="DISPUTES",
        from_type="Payment",
        to_type="Payment",
        properties=["economic_role", "reason"],
        creation_path="financial_normalization.dispute_projection",
    ),
]


# ── Lookup helpers ─────────────────────────────────────────────────────────
# Maps cover commerce AND WP6a financial-reference schemas (registered types).

VERTEX_SCHEMA_MAP: dict[str, VertexSchema] = {
    s.vertex_type: s for s in [*COMMERCE_VERTEX_SCHEMAS, *REFERENCE_VERTEX_SCHEMAS]
}

EDGE_SCHEMA_MAP: dict[str, EdgeSchema] = {
    s.edge_type: s for s in [*COMMERCE_EDGE_SCHEMAS, *REFERENCE_EDGE_SCHEMAS]
}


def get_vertex_schema(vertex_type: str) -> Optional[VertexSchema]:
    return VERTEX_SCHEMA_MAP.get(vertex_type)


def get_edge_schema(edge_type: str) -> Optional[EdgeSchema]:
    return EDGE_SCHEMA_MAP.get(edge_type)
