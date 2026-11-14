"""Reconciled Control Plane — canonical authority reconciliation (Program A).

Post-734, the control plane is an *operational convergence and change-
orchestration* layer. It is deliberately **not** a second credential store, a
second rights authority, a semantic-mapping authority, an SDK artifact
authority, a graph writer, or a release go/no-go authority. This module records
that ownership map once, as data, so engines, routes, docs and tests can cite
one shared statement instead of re-deriving it per surface.

The map is intentionally asymmetric:

* the RCP **owns** convergence: desired-vs-observed reconciliation, bounded
  change planning, rollout coordination, cross-authority evidence correlation,
  and its own activation authority;
* the RCP **observes** the authorities it orchestrates around: provider
  credentials, source rights, semantic/contract compatibility, SDK artifacts,
  readiness decisions, durable ingestion, and canonical identity;
* the RCP **never owns** the decisions themselves.

``assert_authority_map_integrity`` is the fail-closed check: an area the RCP
does not own may never be assigned to it, and an owned area must be assigned to
it. The contract twin lives in ``packages/shared/managed-integrations.ts`` and
is parity-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── vocabularies ─────────────────────────────────────────────────────────────

# Canonical owners of the authorities around the control plane. These are
# existing Aether authorities — the RCP never replaces any of them.
CONTROL_PLANE_AUTHORITY_OWNERS: tuple[str, ...] = (
    "provider_runtime",
    "rights_authority",
    "contract_governance",
    "sdk_distribution",
    "graph_mutation_gateway",
    "ingestion",
    "identity",
    "readiness",
    "reconciled_control_plane",
)

# Every authority area the control plane touches. The first block is external
# (observed, or deliberately no interface); the second block is owned.
RCP_EXTERNAL_AUTHORITY_AREAS: tuple[str, ...] = (
    "provider_credentials",
    "source_rights",
    "schema_semantics",
    "sdk_artifacts",
    "release_readiness",
    "durable_ingestion",
    "canonical_identity",
    "graph_mutation",
)

# The external areas the RCP actually reads (identity and graph writes are
# deliberately no-interface: identity resolution and graph mutation stay wholly
# outside the plane).
RCP_OBSERVED_AUTHORITY_AREAS: tuple[str, ...] = (
    "provider_credentials",
    "source_rights",
    "schema_semantics",
    "sdk_artifacts",
    "release_readiness",
    "durable_ingestion",
)

RCP_NO_INTERFACE_AUTHORITY_AREAS: tuple[str, ...] = (
    "canonical_identity",
    "graph_mutation",
)

RCP_OWNED_AUTHORITY_AREAS: tuple[str, ...] = (
    "operational_convergence",
    "change_planning_and_orchestration",
    "rollout_coordination",
    "control_evidence_correlation",
    "control_plane_activation",
)

CONTROL_PLANE_AUTHORITY_AREAS: tuple[str, ...] = (
    RCP_EXTERNAL_AUTHORITY_AREAS + RCP_OWNED_AUTHORITY_AREAS
)

# How the control plane may interact with an area:
#   own         — the RCP is the canonical decision/storage authority
#   observe     — the RCP reads the owner's state and may orchestrate actions
#   none        — the RCP has no interface; graph writes stay behind the gateway
CONTROL_PLANE_AUTHORITY_ROLES: tuple[str, ...] = ("own", "observe", "none")

# Areas the RCP must never claim. ``graph_mutation`` is separate from schema
# semantics: the Graph Mutation Gateway owns every canonical write.
RCP_FORBIDDEN_AUTHORITY_AREAS: tuple[str, ...] = ("graph_mutation",)


@dataclass(frozen=True)
class ControlPlaneAuthorityAssignment:
    """One canonical owner + the RCP's permitted interface to it."""

    area: str
    owner: str
    rcp_role: str
    interface: tuple[str, ...]
    note: Optional[str] = None


CONTROL_PLANE_AUTHORITY_ASSIGNMENTS: tuple[ControlPlaneAuthorityAssignment, ...] = (
    ControlPlaneAuthorityAssignment(
        area="provider_credentials",
        owner="provider_runtime",
        rcp_role="observe",
        interface=(
            "sensors.observed_from_provider_runtime",
            "governance.reconciler credential-validity drift",
        ),
        note=(
            "Credentials, OAuth, reconnect and provider sync belong to Provider "
            "Runtime. RCP observes health and routes ActionRequired; it never "
            "stores a credential or mints a second authorization lifecycle."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="source_rights",
        owner="rights_authority",
        rcp_role="observe",
        interface=(
            "sensors.observed_from_provider_runtime",
            "reconciler blocked/admission classification",
        ),
        note=(
            "Rights Authority owns admission, retention, use and revocation "
            "(including PR #813 source_relationship decisions). RCP consumes the "
            "decision; it never becomes a second rights authority."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="schema_semantics",
        owner="contract_governance",
        rcp_role="observe",
        interface=(
            "source_authority.SourceAuthorityRuleView",
            "simulation/schema drift findings",
        ),
        note=(
            "Contract Governance / normalization decide canonical schema and "
            "semantic mapping truth. RCP consumes schema_changed / "
            "mapping_candidate_ready / mapping_requires_review findings and "
            "plans reviewable changes; it does not restore the deleted "
            "schema_mapping engine."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="sdk_artifacts",
        owner="sdk_distribution",
        rcp_role="observe",
        interface=(
            "sensors.observed_from_site_install",
            "control_plane.register_site_install",
            "desired_policy release-channel floor",
        ),
        note=(
            "SDK Distribution decides which signed artifacts exist. RCP decides "
            "whether a tenant integration should move to one, through a "
            "ChangeSet/rollout, and never publishes an artifact itself."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="release_readiness",
        owner="readiness",
        rcp_role="observe",
        interface=(
            "activation.ControlPlaneActivationReadinessView",
            "ControlPlaneActivationService advance/resume gate",
        ),
        note=(
            "Readiness is the release and tenant go/no-go authority. RCP supplies "
            "operational facts; activation transitions require a readiness "
            "snapshot and never reinterpret readiness as their own decision."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="durable_ingestion",
        owner="ingestion",
        rcp_role="observe",
        interface=("reconcile_runs evidence", "quarantine/replay findings"),
        note=(
            "Ingestion owns durable acceptance, retries and replay storage. RCP "
            "coordinates recovery/backfill actions and evidence; it never "
            "re-implements the ingest path."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="canonical_identity",
        owner="identity",
        rcp_role="none",
        interface=(),
        note=(
            "Identity owns canonical identity resolution. RCP does not merge, "
            "resolve or write identity state."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="graph_mutation",
        owner="graph_mutation_gateway",
        rcp_role="none",
        interface=(),
        note=(
            "Every canonical graph write stays behind the Graph Mutation "
            "Gateway. RCP is read_only over graph state (spine contract) and "
            "never bypasses the gateway."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="operational_convergence",
        owner="reconciled_control_plane",
        rcp_role="own",
        interface=("reconciler.reconcile", "reconcile_runs"),
        note=(
            "Desired-vs-observed classification over the managed-integration "
            "inventory is the control plane's own authority."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="change_planning_and_orchestration",
        owner="reconciled_control_plane",
        rcp_role="own",
        interface=("change_planning.plan_from_drift", "change_sets"),
        note=(
            "Bounded, risk-assessed ChangeSets and their approved execution are "
            "the control plane's own authority."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="rollout_coordination",
        owner="reconciled_control_plane",
        rcp_role="own",
        interface=("rollout.RolloutEngine", "rollouts"),
        note=(
            "RCP coordinates progressive delivery over artifacts owned by other "
            "authorities; it does not author the artifacts."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="control_evidence_correlation",
        owner="reconciled_control_plane",
        rcp_role="own",
        interface=("execution evidence records", "ActionRequired lifecycle"),
        note=(
            "RCP correlates evidence from rights, consent, audit, provider and "
            "ingestion owners into one explanation. It never duplicates their "
            "source evidence."
        ),
    ),
    ControlPlaneAuthorityAssignment(
        area="control_plane_activation",
        owner="reconciled_control_plane",
        rcp_role="own",
        interface=(
            "activation.ControlPlaneActivationService",
            "rcp_control_plane_activation_states",
        ),
        note=(
            "The control plane's own shadow->detect->plan->R0->R1->R2->fully_"
            "managed activation state is durable and readiness-gated; env flags "
            "are hard kill switches, never activation authority."
        ),
    ),
)

_ASSIGNMENTS_BY_AREA: dict[str, ControlPlaneAuthorityAssignment] = {
    assignment.area: assignment
    for assignment in CONTROL_PLANE_AUTHORITY_ASSIGNMENTS
}


def assignment_for(area: str) -> ControlPlaneAuthorityAssignment:
    """Return the canonical assignment for ``area`` (KeyError when unknown)."""
    return _ASSIGNMENTS_BY_AREA[area]


def owner_of(area: str) -> str:
    """Canonical owner of ``area``."""
    return assignment_for(area).owner


def rcp_role_for(area: str) -> str:
    """The RCP's permitted interface to ``area``: own / observe / none."""
    return assignment_for(area).rcp_role


def assert_authority_map_integrity() -> None:
    """Fail closed when the authority map contradicts itself.

    Raises ``ValueError`` when an assignment names an unknown area/owner/role,
    when an observed area is assigned as owned (or vice versa), when the
    forbidden graph-mutation area is claimed, or when the map has duplicates.
    """
    seen: set[str] = set()
    for assignment in CONTROL_PLANE_AUTHORITY_ASSIGNMENTS:
        area = assignment.area
        if area in seen:
            raise ValueError(f"duplicate authority area {area!r}")
        seen.add(area)
        if area not in CONTROL_PLANE_AUTHORITY_AREAS:
            raise ValueError(f"unknown authority area {area!r}")
        if assignment.owner not in CONTROL_PLANE_AUTHORITY_OWNERS:
            raise ValueError(
                f"unknown authority owner {assignment.owner!r} for {area!r}"
            )
        if assignment.rcp_role not in CONTROL_PLANE_AUTHORITY_ROLES:
            raise ValueError(
                f"unknown RCP role {assignment.rcp_role!r} for {area!r}"
            )
        if area in RCP_FORBIDDEN_AUTHORITY_AREAS and assignment.owner == (
            "reconciled_control_plane"
        ):
            raise ValueError(f"forbidden area {area!r} assigned to the RCP")
        if area in RCP_FORBIDDEN_AUTHORITY_AREAS and assignment.rcp_role != "none":
            raise ValueError(
                f"forbidden area {area!r} must have rcp_role='none', got "
                f"{assignment.rcp_role!r}"
            )
        owned = assignment.owner == "reconciled_control_plane"
        if area in RCP_OWNED_AUTHORITY_AREAS and not owned:
            raise ValueError(
                f"owned area {area!r} assigned to {assignment.owner!r}"
            )
        if area in RCP_EXTERNAL_AUTHORITY_AREAS and owned:
            raise ValueError(
                f"external area {area!r} assigned to the RCP — parallel "
                "authority is forbidden"
            )
        if area in RCP_OBSERVED_AUTHORITY_AREAS and assignment.rcp_role != "observe":
            raise ValueError(
                f"observed area {area!r} must have rcp_role='observe', got "
                f"{assignment.rcp_role!r}"
            )
        if area in RCP_NO_INTERFACE_AUTHORITY_AREAS and assignment.rcp_role != "none":
            raise ValueError(
                f"no-interface area {area!r} must have rcp_role='none', got "
                f"{assignment.rcp_role!r}"
            )
        if area in RCP_OWNED_AUTHORITY_AREAS and assignment.rcp_role != "own":
            raise ValueError(
                f"owned area {area!r} must have rcp_role='own', got "
                f"{assignment.rcp_role!r}"
            )
    missing = set(CONTROL_PLANE_AUTHORITY_AREAS) - seen
    if missing:
        raise ValueError(f"authority map is missing areas: {sorted(missing)}")
    forbidden_missing = set(RCP_FORBIDDEN_AUTHORITY_AREAS) - seen
    if forbidden_missing:
        raise ValueError(
            "authority map must declare forbidden areas: "
            f"{sorted(forbidden_missing)}"
        )


__all__ = [
    "CONTROL_PLANE_AUTHORITY_AREAS",
    "CONTROL_PLANE_AUTHORITY_ASSIGNMENTS",
    "CONTROL_PLANE_AUTHORITY_OWNERS",
    "CONTROL_PLANE_AUTHORITY_ROLES",
    "ControlPlaneAuthorityAssignment",
    "RCP_EXTERNAL_AUTHORITY_AREAS",
    "RCP_FORBIDDEN_AUTHORITY_AREAS",
    "RCP_NO_INTERFACE_AUTHORITY_AREAS",
    "RCP_OBSERVED_AUTHORITY_AREAS",
    "RCP_OWNED_AUTHORITY_AREAS",
    "assert_authority_map_integrity",
    "assignment_for",
    "owner_of",
    "rcp_role_for",
]
