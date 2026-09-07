"""Phase-1 planning half of the Reconciliation Engine (blueprint §32 steps 12-15).

Given the actionable drift a Phase-0 reconcile classifies, this module produces
a typed **ChangeSet plan** — the candidate change, its control-topology blast
radius, its §39 risk classification, and the §32 step-15 automation-authority
decision — and then enforces the §35 concurrency/idempotency guards that make
"never apply a stale ChangeSet" a checkable property.

Nothing here executes anything. A plan is a candidate: it is created ``draft``,
may be promoted to ``planned`` only while its guard revisions are current, and
falls to ``superseded`` when a later reconcile invalidates it. Every other §34
status is unreachable while no executor exists; illegal transitions fail
closed (``with_status`` raises).

Remediation vocabulary: each plan ``ChangeSpec`` names one §36 Day-1
change-action kind. Phase 1 seeds the deterministic remediations (a drift type
x integration-kind → exactly one action, or none). Drift with no deterministic
remediation — e.g. ``schema_drift``, which needs the §38 mapping compiler — does
**not** fabricate a change; it yields no plan and stays surfaced by its
reconcile run.

Risk scoring: ``classify_risk`` applies the §39 classes through an explicit
rules table (R0 trivial → R5 destructive, plus the security-emergency class).
These rules are Phase-1 engine policy — small, transparent, reviewable — not a
stamped production policy; later phases deepen them as actuators bind.

§32 step numbering is cited throughout: 12 candidate ChangeSet, 13 blast
radius, 14 risk, 15 automation authority. The §35 guards appear on every plan.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable, Optional

from services.managed_integrations.contracts import (
    BlastRadiusView,
    ChangeRiskClass,
    ChangeSetPlanView,
    ChangeSetStatus,
    ChangeSpec,
    DriftRecord,
    IntegrationSourceOrigin,
    RiskAssessmentView,
)

# ── remediation registry (drift type x integration kind → action kind) ──────

_TENANT_SDK_KINDS = frozenset(
    {
        "sdk_web",
        "sdk_ios",
        "sdk_android",
        "sdk_react_native",
        "sdk_desktop",
        "sdk_node",
        "sdk_python",
        "sdk_rust",
        "sdk_other",
    }
)

# Aether-hosted runtimes Olympus can release / canary / roll back (§30).
_FULLY_MANAGED_KINDS = frozenset(
    {
        "connector_aether_hosted",
        "provider_runtime_connection",
    }
)


def remediation_action(drift_type: str, integration_kind: str) -> Optional[str]:
    """The deterministic §36 change-action a drift type x kind maps to.

    Returns exactly zero or one action. Drift with no deterministic
    remediation (schema drift needing the §38 compiler, identity/health facts
    that must be reviewed rather than auto-changed, tenant-side runtimes whose
    repository policy governs the change) yields ``None`` — planning never
    fabricates a change for a remediation it cannot actually perform.
    """
    if drift_type == "schema_drift":
        return None  # needs the §38 schema→mapping compiler.
    if drift_type in {"fleet_identity_drift", "health_drift"}:
        # Surface first: identity mismatch and health facts are review/action,
        # not silent mutations (CP-09 explainability, §12.14 ActionRequired).
        return "notification_action"
    if drift_type in {"version_drift", "capability_drift"}:
        if integration_kind in _TENANT_SDK_KINDS:
            # Tenant-side SDK: a repository/build update under tenant repo
            # policy (§30, §31 — repository automation never silently merges).
            return "repository_upgrade"
        if integration_kind == "connector_aether_hosted":
            return "managed_connector_change"
        if integration_kind == "provider_runtime_connection":
            return "provider_runtime_change"
    return None


def _semantic_impact_for(drift_types: Iterable[str]) -> str:
    """Phase-1 default risk signal derived from the drift a change touches.

    Upgrade/capability remediations change runtime behaviour (``behavioral``);
    notification-only remediations are informational (``config``). Schema/data
    remediations never reach a Phase-1 plan, so ``data`` is not produced here.
    """
    for dtype in drift_types:
        if dtype in {"version_drift", "capability_drift"}:
            return "behavioral"
    return "config"


# ── §39 risk engine ──────────────────────────────────────────────────────────

# Semantic-impact scale: none | config | behavioral | data | destructive.
# §39 inputs without a floor do not raise the class; floors only escalate.
# "migration complexity": none | low | medium | high.
# Fleet health: healthy | degraded | unknown.

@dataclass(frozen=True)
class RiskInputs:
    """Observable inputs to the §39 risk engine (see §12.6 RiskAssessment).

    Every field has a neutral default so that a caller must *supply* evidence
    to raise risk — nothing escalates by assumption. ``blast_radius`` is the
    §32 step-13 view; the caller computes it from the control topology.
    """

    blast_radius: BlastRadiusView = field(
        default_factory=lambda: BlastRadiusView(
            integration_count=1, tenant_count=1, environment_count=1
        )
    )
    integration_kind: str = "sdk_web"
    semantic_impact: str = "config"  # none|config|behavioral|data|destructive
    tenant_criticality: str = "standard"  # standard|high
    sensitive_data_impact: str = "none"  # none|pii|financial|special_category|credential
    scope_expansion: bool = False  # new data category/purpose/permission/provider scope
    destructive: bool = False  # destructive / high-consequence change
    runtime_uncertainty: str = "low"  # low|medium|high
    migration_complexity: str = "none"  # none|low|medium|high
    fleet_health: str = "unknown"  # healthy|degraded|unknown
    provider_dependency_risk: str = "low"  # low|medium|high
    rollback_confidence: str = "high"  # high|medium|low
    simulation_completeness: str = "none"  # none|partial|full

    def floor_explanation(self, token: str) -> str:
        return f"R-floor:{token}"


def classify_risk(inputs: RiskInputs) -> tuple[ChangeRiskClass, list[str]]:
    """§39 risk classification from the rules table below.

    Highest floor wins; each applied rule contributes an explanation ref. The
    classes are the §39 set R0 trivial → R5 destructive/high-consequence. The
    security-emergency class is *not* derivable from inputs — it is declared by
    the security authority (see ``assess_risk``).
    """
    refs: list[str] = []
    klass: ChangeRiskClass = "R0"

    def _raise(to: ChangeRiskClass, token: str) -> None:
        nonlocal klass
        order = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
        if order[to] > order[klass]:
            klass = to
            refs.append(inputs.floor_explanation(token))

    br = inputs.blast_radius
    if inputs.destructive or inputs.semantic_impact == "destructive":
        _raise("R5", "destructive")
    if inputs.scope_expansion:
        # New data category / purpose / permission / provider scope: tenant
        # approval (§39 R4).
        _raise("R4", "scope-expansion")
    if inputs.sensitive_data_impact in {"special_category", "credential"}:
        _raise("R3", "sensitive-data")
    if br.tenant_count > 1:
        # A single ChangeSet spanning tenants is an operator aggregate surface.
        _raise("R3", "cross-tenant")
    if inputs.semantic_impact == "data":
        _raise("R2", "data-semantics")
    # Fleet-health signals only raise *behavioural/data* plans; an
    # informational (notification-only) plan is not held back by an unknown or
    # degraded fleet — surfacing the fact is exactly what it is for.
    if inputs.fleet_health == "degraded" and inputs.semantic_impact != "config":
        _raise("R2", "fleet-degraded")
    if inputs.tenant_criticality == "high" and inputs.semantic_impact != "config":
        _raise("R2", "high-criticality")
    if (
        inputs.semantic_impact == "behavioral"
        or inputs.provider_dependency_risk == "high"
        or inputs.runtime_uncertainty == "high"
        or inputs.rollback_confidence == "low"
        or inputs.migration_complexity == "high"
        or (
            inputs.fleet_health == "unknown"
            and inputs.semantic_impact != "config"
        )
    ):
        _raise("R1", "behavioral-or-uncertainty")

    if not refs:
        refs.append(inputs.floor_explanation("trivial"))
    return klass, refs


# §39 execution authority per class.
_AUTOMATION: dict[ChangeRiskClass, tuple[bool, list[str]]] = {
    # (automation_allowed, required gates/approval tokens)
    "R0": (True, []),
    "R1": (True, ["gate:simulation"]),  # simulate/shadow then automatic
    "R2": (True, ["gate:canary", "gate:health"]),  # canary + health-gated
    "R3": (False, ["approval:olympus_operator"]),
    "R4": (False, ["approval:tenant_owner"]),
    "R5": (False, ["approval:governed"]),  # explicit governed approval
    "security_emergency": (False, ["approval:olympus_security"]),
}


def automation_authority(
    risk_class: ChangeRiskClass, *, security_emergency_authorized: bool = False
) -> tuple[bool, list[str]]:
    """§32 step-15 automation-authority decision for a risk class.

    Returns ``(automation_allowed, authority_tokens)``. A security emergency
    becomes automatic only when the Olympus security operator authorizes it
    (Security Blueprint policy); the token list then reflects that authority.
    """
    allowed, tokens = _AUTOMATION[risk_class]
    if risk_class == "security_emergency" and security_emergency_authorized:
        return True, []
    return allowed, tokens


def assess_risk(
    inputs: RiskInputs,
    *,
    security_emergency: bool = False,
    security_emergency_authorized: bool = False,
) -> RiskAssessmentView:
    """Compose §39 classification + §32 step-15 authority into the view."""
    if security_emergency:
        klass: ChangeRiskClass = "security_emergency"
        refs = [inputs.floor_explanation("security-emergency")]
    else:
        klass, refs = classify_risk(inputs)
    allowed, tokens = automation_authority(
        klass, security_emergency_authorized=security_emergency_authorized
    )
    approvals = [t for t in tokens if t.startswith("approval:")]
    gates = [t for t in tokens if t.startswith("gate:")]
    refs.extend(gates)
    return RiskAssessmentView(
        risk_class=klass,
        automation_allowed=allowed,
        required_approval_refs=approvals,
        explanation_refs=refs,
    )


# ── §32-13 control-topology blast radius ─────────────────────────────────────

@dataclass(frozen=True)
class ControlTopologyNode:
    """One managed integration in the control topology a change would reach."""

    managed_integration_id: str
    tenant_id: str
    environment_id: str
    integration_kind: str = "sdk_web"
    source_origin: IntegrationSourceOrigin = "tenant"


def compute_blast_radius(
    nodes: Iterable[ControlTopologyNode],
    actionable_drift_types: Iterable[str],
) -> BlastRadiusView:
    """§32 step-13: aggregate control-topology statistics over a node scope.

    The scope is supplied by the caller (a targeted single integration today;
    cross-integration fan-out — e.g. one mapping revision reaching many
    integrations — composes once a topology registry lands in later phases).
    """
    node_list = list(nodes)
    return BlastRadiusView(
        integration_count=len(node_list),
        tenant_count=len({n.tenant_id for n in node_list}),
        environment_count=len({n.environment_id for n in node_list}),
        source_origins=sorted({n.source_origin for n in node_list}),
        actionable_drift_types=sorted(set(actionable_drift_types)),
    )


# ── candidate plan generation (§32 step 12) ─────────────────────────────────

def _idempotency_key(
    *, reconcile_sequence: str, desired_revision: str, observed_revision: str
) -> str:
    """Deterministic key so re-planning the same reconcile is idempotent (§35)."""
    import hashlib

    digest = hashlib.sha256(
        f"{reconcile_sequence}|{desired_revision}|{observed_revision}".encode()
    ).hexdigest()
    return f"ik_{digest[:20]}"


def build_plan(
    *,
    managed_integration_ref: str,
    tenant_id: str,
    environment_id: str,
    desired_revision: str,
    observed_revision: str,
    reconcile_sequence: str,
    drift: Iterable[DriftRecord],
    initiator: str,
    policy_ref: Optional[str] = None,
    reason: Optional[str] = None,
    integration_kind: str = "sdk_web",
    source_origin: IntegrationSourceOrigin = "tenant",
    scope_nodes: Optional[Iterable[ControlTopologyNode]] = None,
    risk_inputs_override: Optional[RiskInputs] = None,
    changeset_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[ChangeSetPlanView]:
    """Generate a candidate ChangeSet from actionable drift (§32 step 12).

    Builds exactly one ``ChangeSpec`` per deterministic remediation; drift with
    no remediation yields **no** fabricated change. Returns ``None`` when no
    change is deterministically plan-able (the drift stays surfaced by the
    reconcile run as review/action). The plan is created ``draft`` with the §35
    guard revisions it was planned against; promotion is a separate, guarded
    step.
    """
    records = list(drift)
    created = now or datetime.now(timezone.utc)

    changes: list[ChangeSpec] = []
    touched: set[str] = set()
    for rec in records:
        action = remediation_action(rec.drift_type, integration_kind)
        if action is None:
            continue
        changes.append(
            ChangeSpec(
                action=action,  # type: ignore[arg-type]
                target_ref=rec.managed_integration_ref,
                params=None,
                reason=rec.detail,
            )
        )
        touched.add(rec.drift_type)

    if not changes:
        return None

    if scope_nodes is None:
        scope_nodes = [
            ControlTopologyNode(
                managed_integration_id=managed_integration_ref,
                tenant_id=tenant_id,
                environment_id=environment_id,
                integration_kind=integration_kind,
                source_origin=source_origin,
            )
        ]
    blast_radius = compute_blast_radius(scope_nodes, touched)

    if risk_inputs_override is not None:
        risk_inputs = replace(
            risk_inputs_override,
            blast_radius=blast_radius,
            integration_kind=integration_kind,
        )
    else:
        risk_inputs = RiskInputs(
            blast_radius=blast_radius,
            integration_kind=integration_kind,
            semantic_impact=_semantic_impact_for(touched),
            simulation_completeness="none",
        )
    risk = assess_risk(risk_inputs)

    plan_reason = reason or _default_reason(records, touched)
    return ChangeSetPlanView(
        changeset_id=changeset_id or f"rcs_{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_id,
        environment_id=environment_id,
        integration_scope=[managed_integration_ref],
        desired_revision=desired_revision,
        observed_revision=observed_revision,
        reconcile_sequence=reconcile_sequence,
        idempotency_key=_idempotency_key(
            reconcile_sequence=reconcile_sequence,
            desired_revision=desired_revision,
            observed_revision=observed_revision,
        ),
        changes=changes,
        reason=plan_reason,
        initiator=initiator,
        policy_ref=policy_ref,
        risk=risk,
        blast_radius=blast_radius,
        status="draft",
        created_at=created,
    )


def _default_reason(
    records: list[DriftRecord], touched: set[str]
) -> str:
    types = ", ".join(sorted(touched)) or "none"
    total = len(records)
    planned = len(touched)
    return (
        f"candidate plan from {planned}/{total} actionable drift "
        f"({types}); drift without a deterministic remediation is "
        "surfaced as review/action, not silently skipped"
    )


# ── §35 concurrency + idempotency guards ─────────────────────────────────────

@dataclass(frozen=True)
class GuardVerdict:
    """Whether a plan may proceed given the *current* guard revisions."""

    ok: bool
    reason: Optional[str] = None


def validate_guards(
    plan: ChangeSetPlanView,
    *,
    current_desired_revision: str,
    current_observed_revision: str,
) -> GuardVerdict:
    """§35: never apply a stale ChangeSet.

    The plan is current only while both guard revisions still match. If the
    desired state advanced or critical observed state changed since planning,
    the plan must be invalidated and reconciliation must run again.
    """
    if current_desired_revision != plan.desired_revision:
        return GuardVerdict(
            False,
            "desired_revision advanced "
            f"({plan.desired_revision} -> {current_desired_revision}); "
            "reconcile again before applying",
        )
    if current_observed_revision != plan.observed_revision:
        return GuardVerdict(
            False,
            "critical observed state changed "
            f"({plan.observed_revision} -> {current_observed_revision}); "
            "reconcile again before applying",
        )
    return GuardVerdict(True)


# ── Phase-1 §34 transitions (illegal transitions fail closed) ────────────────

# Reachable Phase-1 transitions only. Execution statuses (ready, rolling_out,
# committed, ...) are deliberately absent: no executor exists yet, so nothing
# may move a plan toward them. Cancelling a never-executed plan is benign and
# stays legal; superseding records the guard invalidation.
_PHASE1_TRANSITIONS: dict[ChangeSetStatus, frozenset[ChangeSetStatus]] = {
    "draft": frozenset({"planned", "superseded", "cancelled"}),
    "planned": frozenset({"superseded", "cancelled"}),
    "superseded": frozenset(),
    "cancelled": frozenset(),
}


def with_status(
    plan: ChangeSetPlanView,
    status: ChangeSetStatus,
    *,
    now: Optional[datetime] = None,
) -> ChangeSetPlanView:
    """Return a copy of the plan in ``status``, enforcing Phase-1 legality.

    ``draft|planned -> superseded`` records a guard invalidation;
    ``draft|planned -> cancelled`` withdraws a never-executed plan. Any move
    toward an execution status raises until an executor exists (§34: illegal
    transitions fail closed).
    """
    legal = _PHASE1_TRANSITIONS.get(plan.status, frozenset())
    if status not in legal:
        raise ValueError(
            f"illegal ChangeSet transition {plan.status} -> {status} "
            "(illegal transitions fail closed; executor not yet present)"
        )
    created = now or datetime.now(timezone.utc)
    return plan.model_copy(
        update={
            "status": status,
            "superseded_at": created if status == "superseded" else plan.superseded_at,
        }
    )
