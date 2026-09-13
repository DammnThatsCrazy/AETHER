"""Kyber capability vocabulary.

A capability is the *name* a route declares in the route registry. It is not a
second authorization engine: each capability resolves to a
``(GovernanceDomain, PermissionAction, PermissionScope)`` triple that the
existing :class:`services.security.access_control.AccessControlService`
evaluates, plus the two extra dimensions Kyber needs and the governance model
does not carry — a disclosure ceiling and an action class.

This is deliberately granular. There is no ``canViewAll``: the ability to read
fleet aggregates does not imply reading one tenant, reading a tenant does not
imply reading raw evidence, and no read capability implies any command.

Action classes (used by the command plane in a later PR, declared here so the
route registry can classify against a stable vocabulary):

    0  read / search / compare
    1  note / acknowledge
    2  retry / requeue
    3  recompute / replay a bounded window
    4  pause / rollback / high-impact tenant action
    5  fleet-wide / global / destructive action
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from services.security.contracts import (
    GovernanceDomain,
    PermissionAction,
    PermissionScope,
)

from .disclosure import DisclosureLevel

# Action classes. Anything above READ requires an explicit command capability;
# anything at or above HIGH_IMPACT requires fresh step-up plus (per policy) a
# dry run, a blast-radius review, a rollback plan and a verification plan.
ACTION_CLASS_READ = 0
ACTION_CLASS_ANNOTATE = 1
ACTION_CLASS_RETRY = 2
ACTION_CLASS_RECOMPUTE = 3
ACTION_CLASS_HIGH_IMPACT = 4
ACTION_CLASS_FLEET_DESTRUCTIVE = 5

MAX_ACTION_CLASS = ACTION_CLASS_FLEET_DESTRUCTIVE

# Action classes that always demand a fresh step-up grant, whatever the role.
STEP_UP_ACTION_CLASSES = frozenset({ACTION_CLASS_HIGH_IMPACT, ACTION_CLASS_FLEET_DESTRUCTIVE})


@dataclass(frozen=True)
class Capability:
    """One named unit of Kyber authority."""

    capability_id: str
    domain: GovernanceDomain
    action: PermissionAction
    scope: PermissionScope
    action_class: int
    max_disclosure: DisclosureLevel
    description: str
    #: True when the capability names one tenant and therefore needs an active,
    #: purpose-bound tenant access scope naming that same tenant.
    tenant_scoped: bool = False

    @property
    def requires_step_up(self) -> bool:
        return self.action_class in STEP_UP_ACTION_CLASSES

    @property
    def is_command(self) -> bool:
        return self.action_class > ACTION_CLASS_ANNOTATE


def _cap(
    capability_id: str,
    domain: GovernanceDomain,
    action: PermissionAction,
    scope: PermissionScope,
    action_class: int,
    max_disclosure: DisclosureLevel,
    description: str,
    *,
    tenant_scoped: bool = False,
) -> Capability:
    return Capability(
        capability_id=capability_id,
        domain=domain,
        action=action,
        scope=scope,
        action_class=action_class,
        max_disclosure=max_disclosure,
        description=description,
        tenant_scoped=tenant_scoped,
    )


_D = DisclosureLevel

# ── Canonical capability catalog ──────────────────────────────────────────────
#
# Command capabilities (kyber.command.*) are declared here so the route registry
# has a stable vocabulary to classify against; their routes arrive with the
# command plane. Declaring them early costs nothing and prevents the registry
# schema from changing again when those routes land.

CAPABILITIES: dict[str, Capability] = {
    c.capability_id: c
    for c in (
        # Platform / fleet — aggregates only, never a single tenant's records.
        _cap("kyber.platform.health.read", "kyber_admin", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D1_FLEET_AGGREGATE,
             "Platform and fleet health aggregates."),
        _cap("kyber.platform.cost.read", "billing", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D1_FLEET_AGGREGATE,
             "Platform cost and spend aggregates."),
        _cap("kyber.platform.release.read", "kyber_admin", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D0_PLATFORM_TOPOLOGY,
             "Releases, deployments and configuration versions."),

        # Graph — topology, then fleet, then cohort, then one scoped tenant.
        _cap("kyber.graph.platform.read", "graph", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D0_PLATFORM_TOPOLOGY,
             "Platform graph topology: services, features, dependencies."),
        _cap("kyber.graph.fleet.read", "graph", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D1_FLEET_AGGREGATE,
             "Fleet-wide graph health aggregates."),
        _cap("kyber.graph.cohort.read", "graph", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D1_FLEET_AGGREGATE,
             "Cohort graph aggregates, subject to minimum cohort size."),
        _cap("kyber.graph.tenant.read", "graph", "read", "assigned_tenant",
             ACTION_CLASS_READ, _D.D3_TENANT_VISIBLE,
             "One tenant's graph, through the scoped tenant gateway.",
             tenant_scoped=True),
        _cap("kyber.graph.evidence.read", "graph", "read", "assigned_tenant",
             ACTION_CLASS_READ, _D.D4_EVENT_EVIDENCE,
             "Graph lineage and evidence references for one tenant.",
             tenant_scoped=True),

        # Tenant inspection. `mirror.read` reproduces exactly what the tenant
        # sees; `mirror.read_masked` is the same surface with identifiers
        # masked; `raw.read` is unmasked record-level access and is always
        # step-up gated by its disclosure level.
        _cap("kyber.tenant.mirror.read_masked", "kyber_tenant", "read", "assigned_tenant",
             ACTION_CLASS_READ, _D.D2_TENANT_MASKED,
             "Masked tenant summary — identifiers redacted.",
             tenant_scoped=True),
        _cap("kyber.tenant.mirror.read", "kyber_tenant", "read", "assigned_tenant",
             ACTION_CLASS_READ, _D.D3_TENANT_VISIBLE,
             "Tenant Mirror — exactly the tenant-visible Aether result.",
             tenant_scoped=True),
        _cap("kyber.tenant.raw.read", "kyber_tenant", "read", "assigned_tenant",
             ACTION_CLASS_READ, _D.D5_RAW_EVIDENCE,
             "Unmasked raw tenant records. Always step-up gated.",
             tenant_scoped=True),

        # Incidents.
        _cap("kyber.incident.read", "reliability", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D1_FLEET_AGGREGATE,
             "Read incidents, signals and investigations."),
        _cap("kyber.incident.manage", "reliability", "write", "all_tenants_admin",
             ACTION_CLASS_ANNOTATE, _D.D4_EVENT_EVIDENCE,
             "Annotate, assign and update incidents."),
        _cap("kyber.incident.close", "reliability", "approve", "all_tenants_admin",
             ACTION_CLASS_ANNOTATE, _D.D4_EVENT_EVIDENCE,
             "Resolve and close an incident."),

        # Command plane (routes land with the command plane PR).
        _cap("kyber.command.retry", "kyber_command", "dispatch", "assigned_tenant",
             ACTION_CLASS_RETRY, _D.D4_EVENT_EVIDENCE,
             "Retry a failed job or unit of work.", tenant_scoped=True),
        _cap("kyber.command.requeue", "kyber_command", "dispatch", "assigned_tenant",
             ACTION_CLASS_RETRY, _D.D4_EVENT_EVIDENCE,
             "Requeue an import or pipeline run.", tenant_scoped=True),
        _cap("kyber.command.replay", "kyber_command", "dispatch", "assigned_tenant",
             ACTION_CLASS_RECOMPUTE, _D.D4_EVENT_EVIDENCE,
             "Replay a bounded event range.", tenant_scoped=True),
        _cap("kyber.command.recompute", "kyber_command", "dispatch", "assigned_tenant",
             ACTION_CLASS_RECOMPUTE, _D.D4_EVENT_EVIDENCE,
             "Recompute a measurement or projection over a bounded window.",
             tenant_scoped=True),
        _cap("kyber.command.rebuild", "kyber_command", "dispatch", "assigned_tenant",
             ACTION_CLASS_RECOMPUTE, _D.D4_EVENT_EVIDENCE,
             "Rebuild a graph projection.", tenant_scoped=True),
        _cap("kyber.command.pause", "kyber_command", "configure", "assigned_tenant",
             ACTION_CLASS_HIGH_IMPACT, _D.D4_EVENT_EVIDENCE,
             "Pause a connector, ingestion path or worker.", tenant_scoped=True),
        _cap("kyber.command.rollback", "kyber_command", "approve", "all_tenants_admin",
             ACTION_CLASS_HIGH_IMPACT, _D.D4_EVENT_EVIDENCE,
             "Roll back a model or release."),
        _cap("kyber.command.kill_switch", "kyber_command", "admin", "all_tenants_admin",
             ACTION_CLASS_FLEET_DESTRUCTIVE, _D.D4_EVENT_EVIDENCE,
             "Activate a scoped or global kill switch / safe mode."),

        # Exports and governance reads.
        # An export derives an artifact from data the caller may already read;
        # it changes no platform state, so it is class 1 rather than a
        # recompute. Its risk lives in the disclosure ceiling, not the class.
        _cap("kyber.export.create", "audit_exports", "export", "assigned_tenant",
             ACTION_CLASS_ANNOTATE, _D.D4_EVENT_EVIDENCE,
             "Create an operator export.", tenant_scoped=True),
        _cap("kyber.audit.read", "security", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D4_EVENT_EVIDENCE,
             "Read the security audit ledger and access decisions."),
        _cap("kyber.policy.read", "governance", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D1_FLEET_AGGREGATE,
             "Read policy, consent coverage and disclosure decisions."),

        # Reconciled control plane — operator-only convergence + decision
        # evidence over managed integrations (fleet inventory, change-set
        # plans, approvals, action-required review items). The domain carries
        # no tenant grant; the whole surface is operator-derived records that
        # never exist for tenants, so evidence-level disclosure.
        _cap("kyber.reconciled_control.read", "reconciled_control", "read",
             "all_tenants_aggregate", ACTION_CLASS_READ, _D.D4_EVENT_EVIDENCE,
             "Reconciled control plane: managed-integration convergence, "
             "change-set plans and operator decision evidence."),

        # Workforce administration. Separated from every read capability so an
        # operator who can see everything still cannot grant themselves more.
        _cap("kyber.device.approve", "kyber_workforce", "approve", "all_tenants_admin",
             ACTION_CLASS_HIGH_IMPACT, _D.D1_FLEET_AGGREGATE,
             "Approve, suspend or revoke a trusted personal device."),
        _cap("kyber.workforce.manage", "kyber_workforce", "admin", "all_tenants_admin",
             ACTION_CLASS_HIGH_IMPACT, _D.D1_FLEET_AGGREGATE,
             "Invite, suspend and offboard workforce principals."),
        _cap("kyber.role.manage", "kyber_workforce", "admin", "all_tenants_admin",
             ACTION_CLASS_FLEET_DESTRUCTIVE, _D.D1_FLEET_AGGREGATE,
             "Assign or remove role bindings and capability grants."),
        _cap("kyber.workforce.self.read", "kyber_workforce", "read", "all_tenants_aggregate",
             ACTION_CLASS_READ, _D.D0_PLATFORM_TOPOLOGY,
             "Read one's own principal, session, device and capability state."),
    )
}

#: Capability every authenticated workforce principal holds implicitly. It
#: exposes only the caller's own identity state, never anyone else's.
SELF_CAPABILITY = "kyber.workforce.self.read"

ALL_CAPABILITY_IDS: frozenset[str] = frozenset(CAPABILITIES)

COMMAND_CAPABILITY_IDS: frozenset[str] = frozenset(
    cid for cid, cap in CAPABILITIES.items() if cap.is_command
)

TENANT_SCOPED_CAPABILITY_IDS: frozenset[str] = frozenset(
    cid for cid, cap in CAPABILITIES.items() if cap.tenant_scoped
)


def get_capability(capability_id: str) -> Optional[Capability]:
    """Look up a capability, or ``None`` when the id is unknown."""
    return CAPABILITIES.get(capability_id)


def require_capability(capability_id: str) -> Capability:
    """Look up a capability, raising when the id is unknown.

    Used by the route registry loader so a typo in a route declaration is a
    startup failure rather than a silently unenforced route.
    """
    cap = CAPABILITIES.get(capability_id)
    if cap is None:
        raise KeyError(f"unknown Kyber capability: {capability_id}")
    return cap


def expand(capability_ids: Iterable[str]) -> list[Capability]:
    """Resolve ids to capabilities, skipping unknown ids."""
    return [CAPABILITIES[c] for c in capability_ids if c in CAPABILITIES]
