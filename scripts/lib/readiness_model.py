#!/usr/bin/env python3
"""Aether multidimensional readiness model — pure-stdlib core.

This module is the single evaluator behind every readiness report and gate. It
loads the model vocabulary (``config/readiness_model.yaml``) and the feature
records (``config/readiness/features/*.yaml``), enforces the honesty rules, and
computes — per feature, per release profile — a disposition that is decided by
*hard gates*, never by averaging percentages.

Design commitments (see config/readiness_model.yaml for the narrative):

* Implementation completion is repository-controlled ONLY. A missing credential,
  unprovisioned infrastructure, an absent provider account, or missing live
  traffic can never reduce it. Those are recorded as activation blockers and
  environment-evidence gaps.
* Every percentage carries an explicit denominator (the in-scope weighted
  control set) and is computed over in-scope controls only.
* ``intrinsic`` readiness is the feature's own state; ``effective`` readiness
  additionally accounts for unsatisfied hard dependencies. A dependency failure
  never rewrites the feature's intrinsic implementation completion.

No third-party dependencies: this runs on the same bare interpreter as the rest
of ``scripts/`` (no pydantic, no jsonschema).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = ROOT / "config" / "readiness_model.yaml"
FEATURES_DIR = ROOT / "config" / "readiness" / "features"

# ---------------------------------------------------------------------------
# Closed vocabularies (kept here as the authoritative python-side copy; the
# validator cross-checks them against config/readiness_model.yaml so the two
# can never drift).
# ---------------------------------------------------------------------------
IMPLEMENTATION_STATES = [
    "NOT_STARTED",
    "SCAFFOLDED",
    "IMPLEMENTED",
    "RUNTIME_INTEGRATED",
    "VERIFIED",
    "TURNKEY",
]
IMPLEMENTATION_RANK = {s: i * 10 for i, s in enumerate(IMPLEMENTATION_STATES)}

CEILINGS = [
    "CODE_COMPLETE",
    "RUNTIME_INTEGRATED",
    "VERIFIED",
    "CREDENTIAL_TURNKEY",
    "INFRASTRUCTURE_TURNKEY",
    "RELEASE_TURNKEY",
    "LIVE_VERIFIED",
    "SCALE_VERIFIED",
]
# The minimum implementation state a ceiling implies.
CEILING_MIN_STATE = {
    "CODE_COMPLETE": "IMPLEMENTED",
    "RUNTIME_INTEGRATED": "RUNTIME_INTEGRATED",
    "VERIFIED": "VERIFIED",
    "CREDENTIAL_TURNKEY": "TURNKEY",
    "INFRASTRUCTURE_TURNKEY": "TURNKEY",
    "RELEASE_TURNKEY": "TURNKEY",
    "LIVE_VERIFIED": "TURNKEY",
    "SCALE_VERIFIED": "TURNKEY",
}
# Ceilings whose achievement requires evidence beyond the repository.
CEILINGS_REQUIRING_EXTERNAL_EVIDENCE = {"LIVE_VERIFIED", "SCALE_VERIFIED"}

ACTIVATION_STATES = [
    "NO_EXTERNAL_BLOCKER",
    "CREDENTIAL_WAITING",
    "INFRASTRUCTURE_WAITING",
    "ACCOUNT_WAITING",
    "REGISTRATION_WAITING",
    "DNS_WAITING",
    "EXTERNAL_APPROVAL_WAITING",
    "AUDIT_WAITING",
    "LIVE_DATA_WAITING",
    "ENVIRONMENT_ACCESS_WAITING",
    "ENVIRONMENT_VALIDATION_PENDING",
]
# Blocker types are the activation states except the "no blocker" sentinel.
BLOCKER_TYPES = [s for s in ACTIVATION_STATES if s != "NO_EXTERNAL_BLOCKER"]

ENVIRONMENT_STATES = [
    "NOT_APPLICABLE",
    "NOT_ATTEMPTED",
    "BLOCKED_EXTERNAL",
    "FAILED",
    "VERIFIED",
    "EXPIRED",
]
ENVIRONMENTS = [
    "local",
    "ci",
    "integration",
    "preview",
    "demo",
    "staging",
    "pilot",
    "production",
    "scale",
]

CONFIDENCE_LEVELS = ["UNPROVEN", "LOW", "MODERATE", "HIGH", "VERY_HIGH"]
CONFIDENCE_RANK = {c: i for i, c in enumerate(CONFIDENCE_LEVELS)}

DEPENDENCY_STATES = ["SATISFIED", "WAITING", "BLOCKED", "UNKNOWN"]
PARTICIPATION_STATES = [
    "required",
    "experimental",
    "disabled_intentionally",
    "not_in_release",
]

DISPOSITIONS = [
    "NOT_IN_PROFILE",
    "DISABLED_INTENTIONALLY",
    "BLOCKED_BY_CODE",
    "BLOCKED_BY_PRODUCTIONIZATION",
    "BLOCKED_BY_DEPENDENCY",
    "READY_TO_ACTIVATE",
    "READY_TO_VALIDATE",
    "TECHNICALLY_RELEASE_ELIGIBLE",
    "BUSINESS_READINESS_PENDING",
    "PILOT_ELIGIBLE",
    "PRODUCTION_ELIGIBLE",
    "LIVE_VERIFIED",
    "SCALE_VERIFIED",
]
# Ascending readiness order used to reduce a profile to its weakest required
# capability. NOT_IN_PROFILE / DISABLED_INTENTIONALLY are excluded from the
# reduction (they are not "blocking" — they are out of scope on purpose).
DISPOSITION_ORDER = [
    "BLOCKED_BY_CODE",
    "BLOCKED_BY_DEPENDENCY",
    "BLOCKED_BY_PRODUCTIONIZATION",
    "READY_TO_ACTIVATE",
    "READY_TO_VALIDATE",
    "BUSINESS_READINESS_PENDING",
    "TECHNICALLY_RELEASE_ELIGIBLE",
    "PILOT_ELIGIBLE",
    "PRODUCTION_ELIGIBLE",
    "LIVE_VERIFIED",
    "SCALE_VERIFIED",
]
DISPOSITION_RANK = {d: i for i, d in enumerate(DISPOSITION_ORDER)}

BLOCKING_DISPOSITIONS = {
    "BLOCKED_BY_CODE",
    "BLOCKED_BY_PRODUCTIONIZATION",
    "BLOCKED_BY_DEPENDENCY",
}
ELIGIBLE_DISPOSITIONS = {
    "TECHNICALLY_RELEASE_ELIGIBLE",
    "PILOT_ELIGIBLE",
    "PRODUCTION_ELIGIBLE",
    "LIVE_VERIFIED",
    "SCALE_VERIFIED",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class Control:
    id: str
    weight: float
    satisfied: bool
    description: str = ""
    rationale: str = ""
    evidence: list[str] = field(default_factory=list)
    in_scope: bool = True


@dataclass
class Blocker:
    type: str
    description: str
    owner: str
    required_action: str
    source_code_change_expected: bool
    affected_environments: list[str] = field(default_factory=list)
    affected_release_profiles: list[str] = field(default_factory=list)
    evidence_required: str = ""


@dataclass
class Dependency:
    feature_id: str
    state: str
    version_constraint: str = ""
    required_profile: str = ""
    prevents: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class EnvironmentRecord:
    state: str
    evidence: list[str] = field(default_factory=list)
    verified_at: Optional[str] = None
    verification_method: Optional[str] = None
    environment_identifier: Optional[str] = None
    credentialed: Optional[bool] = None
    suite: Optional[str] = None
    revalidation_policy: Optional[str] = None
    expires_at: Optional[str] = None
    failure_summary: Optional[str] = None


@dataclass
class ProfileParticipation:
    participation: str
    implementation_floor: Optional[str] = None
    productionization_required: Optional[bool] = None
    environment_gate: Optional[str] = None
    business_gate: Optional[bool] = None
    note: str = ""


@dataclass
class Scope:
    id: str
    version: int
    target: str
    title: str = ""
    included: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    release_profile_applicability: list[str] = field(default_factory=list)


@dataclass
class Ceiling:
    type: str
    achieved: bool
    achieved_at: Optional[str] = None
    remaining_after_ceiling: list[str] = field(default_factory=list)
    remaining_is_repository_controlled: bool = False
    evidence: list[str] = field(default_factory=list)


@dataclass
class ControlBlock:
    controls: list[Control]
    denominator: str = ""
    remaining_work: list[str] = field(default_factory=list)
    state: Optional[str] = None  # only implementation carries this

    def percent(self) -> float:
        return completion_percent(self.controls)

    def denominator_weight(self) -> float:
        return sum(c.weight for c in self.controls if c.in_scope)

    def complete(self) -> bool:
        return self.percent() >= 100.0 and not self.remaining_work


@dataclass
class Confidence:
    level: str
    reasons: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)


@dataclass
class OperationalOwnership:
    team: Optional[str] = None
    technical_owner: Optional[str] = None
    operational_owner: Optional[str] = None
    escalation: Optional[str] = None
    runbook: Optional[str] = None
    dashboards: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    service_level_target: Optional[str] = None
    recovery_objective: Optional[str] = None
    manual_procedures: list[str] = field(default_factory=list)
    on_call: Any = None

    def is_present(self) -> bool:
        """Minimum operational ownership for a production-eligible capability:
        an owning team, a runbook, an alert destination, and a dashboard."""
        return bool(self.team and self.runbook and self.alerts and self.dashboards)


@dataclass
class FeatureRecord:
    feature_id: str
    title: str
    scope: Scope
    repository_ceiling: Ceiling
    implementation: ControlBlock
    productionization: ControlBlock
    activation_state: str
    activation_blockers: list[Blocker]
    environment_evidence: dict[str, EnvironmentRecord]
    confidence: Confidence
    release_profiles: dict[str, ProfileParticipation]
    summary: str = ""
    owning_system: str = ""
    hard_dependencies: list[Dependency] = field(default_factory=list)
    soft_dependencies: list[Dependency] = field(default_factory=list)
    optional_dependencies: list[Dependency] = field(default_factory=list)
    operational_ownership: OperationalOwnership = field(default_factory=OperationalOwnership)
    business_applicable: bool = False
    business: ControlBlock = field(default_factory=lambda: ControlBlock(controls=[]))
    historical: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""


# ---------------------------------------------------------------------------
# Percentages (rule 1: every percentage names its denominator; rule 2: only
# in-scope requirements count)
# ---------------------------------------------------------------------------
def completion_percent(controls: list[Control]) -> float:
    """Weighted coverage over in-scope controls. Returns 100.0 when there are no
    in-scope controls (vacuously complete — an empty requirement set)."""
    in_scope = [c for c in controls if c.in_scope]
    total = sum(c.weight for c in in_scope)
    if total <= 0:
        return 100.0
    got = sum(c.weight for c in in_scope if c.satisfied)
    return round(got / total * 100.0, 2)


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------
@dataclass
class ProfileSpec:
    id: str
    title: str
    deployment_profile: Optional[str]
    implementation_floor: str
    productionization_required: bool
    environment_gate: Optional[str]
    business_gate: bool


@dataclass
class ReadinessModel:
    profiles: dict[str, ProfileSpec]
    credentialed_environments: set[str]
    raw: dict[str, Any]

    @property
    def profile_ids(self) -> list[str]:
        return list(self.profiles.keys())


def load_model(root: Path = ROOT) -> ReadinessModel:
    data = yaml.safe_load((root / "config" / "readiness_model.yaml").read_text())
    profiles: dict[str, ProfileSpec] = {}
    for pid, spec in (data.get("release_profiles") or {}).items():
        profiles[pid] = ProfileSpec(
            id=pid,
            title=spec.get("title", pid),
            deployment_profile=spec.get("deployment_profile"),
            implementation_floor=spec.get("implementation_floor", "TURNKEY"),
            productionization_required=bool(spec.get("productionization_required", True)),
            environment_gate=spec.get("environment_gate"),
            business_gate=bool(spec.get("business_gate", False)),
        )
    return ReadinessModel(
        profiles=profiles,
        credentialed_environments=set(data.get("credentialed_environments") or []),
        raw=data,
    )


# ---------------------------------------------------------------------------
# Loading feature records
# ---------------------------------------------------------------------------
def _controls(raw: Any) -> list[Control]:
    out: list[Control] = []
    for c in raw or []:
        out.append(
            Control(
                id=c["id"],
                weight=float(c["weight"]),
                satisfied=bool(c["satisfied"]),
                description=c.get("description", ""),
                rationale=c.get("rationale", ""),
                evidence=list(c.get("evidence", []) or []),
                in_scope=bool(c.get("in_scope", True)),
            )
        )
    return out


def _control_block(raw: Any, *, with_state: bool = False) -> ControlBlock:
    raw = raw or {}
    return ControlBlock(
        controls=_controls(raw.get("controls")),
        denominator=raw.get("denominator", ""),
        remaining_work=list(raw.get("remaining_work", []) or []),
        state=raw.get("state") if with_state else None,
    )


def _dependencies(raw: Any) -> list[Dependency]:
    out: list[Dependency] = []
    for d in raw or []:
        out.append(
            Dependency(
                feature_id=d["feature_id"],
                state=d["state"],
                version_constraint=d.get("version_constraint", ""),
                required_profile=d.get("required_profile", ""),
                prevents=list(d.get("prevents", []) or []),
                note=d.get("note", ""),
            )
        )
    return out


def feature_from_dict(data: dict[str, Any], source_path: str = "") -> FeatureRecord:
    scope_raw = data.get("scope") or {}
    scope = Scope(
        id=scope_raw.get("id", ""),
        version=int(scope_raw.get("version", 1)),
        target=scope_raw.get("target", ""),
        title=scope_raw.get("title", ""),
        included=list(scope_raw.get("included", []) or []),
        excluded=list(scope_raw.get("excluded", []) or []),
        deferred=list(scope_raw.get("deferred", []) or []),
        release_profile_applicability=list(scope_raw.get("release_profile_applicability", []) or []),
    )
    ceil_raw = data.get("repository_ceiling") or {}
    ceiling = Ceiling(
        type=ceil_raw.get("type", ""),
        achieved=bool(ceil_raw.get("achieved", False)),
        achieved_at=ceil_raw.get("achieved_at"),
        remaining_after_ceiling=list(ceil_raw.get("remaining_after_ceiling", []) or []),
        remaining_is_repository_controlled=bool(ceil_raw.get("remaining_is_repository_controlled", False)),
        evidence=list(ceil_raw.get("evidence", []) or []),
    )
    env_ev: dict[str, EnvironmentRecord] = {}
    for env, rec in (data.get("environment_evidence") or {}).items():
        rec = rec or {}
        env_ev[env] = EnvironmentRecord(
            state=rec.get("state", "NOT_ATTEMPTED"),
            evidence=list(rec.get("evidence", []) or []),
            verified_at=rec.get("verified_at"),
            verification_method=rec.get("verification_method"),
            environment_identifier=rec.get("environment_identifier"),
            credentialed=rec.get("credentialed"),
            suite=rec.get("suite"),
            revalidation_policy=rec.get("revalidation_policy"),
            expires_at=rec.get("expires_at"),
            failure_summary=rec.get("failure_summary"),
        )
    profiles: dict[str, ProfileParticipation] = {}
    for pid, pr in (data.get("release_profiles") or {}).items():
        pr = pr or {}
        profiles[pid] = ProfileParticipation(
            participation=pr.get("participation", "not_in_release"),
            implementation_floor=pr.get("implementation_floor"),
            productionization_required=pr.get("productionization_required"),
            environment_gate=pr.get("environment_gate"),
            business_gate=pr.get("business_gate"),
            note=pr.get("note", ""),
        )
    own_raw = data.get("operational_ownership") or {}
    ownership = OperationalOwnership(
        team=own_raw.get("team"),
        technical_owner=own_raw.get("technical_owner"),
        operational_owner=own_raw.get("operational_owner"),
        escalation=own_raw.get("escalation"),
        runbook=own_raw.get("runbook"),
        dashboards=list(own_raw.get("dashboards", []) or []),
        alerts=list(own_raw.get("alerts", []) or []),
        service_level_target=own_raw.get("service_level_target"),
        recovery_objective=own_raw.get("recovery_objective"),
        manual_procedures=list(own_raw.get("manual_procedures", []) or []),
        on_call=own_raw.get("on_call"),
    )
    activation = data.get("activation") or {}
    blockers = [
        Blocker(
            type=b["type"],
            description=b["description"],
            owner=b["owner"],
            required_action=b["required_action"],
            source_code_change_expected=bool(b["source_code_change_expected"]),
            affected_environments=list(b.get("affected_environments", []) or []),
            affected_release_profiles=list(b.get("affected_release_profiles", []) or []),
            evidence_required=b.get("evidence_required", ""),
        )
        for b in (activation.get("blockers") or [])
    ]
    deps = data.get("dependencies") or {}
    conf = data.get("confidence") or {}
    biz = data.get("business_readiness") or {}
    return FeatureRecord(
        feature_id=data["feature_id"],
        title=data["title"],
        summary=data.get("summary", ""),
        owning_system=data.get("owning_system", ""),
        scope=scope,
        repository_ceiling=ceiling,
        implementation=_control_block(data.get("implementation"), with_state=True),
        productionization=_control_block(data.get("productionization")),
        activation_state=activation.get("state", "NO_EXTERNAL_BLOCKER"),
        activation_blockers=blockers,
        environment_evidence=env_ev,
        confidence=Confidence(
            level=conf.get("level", "UNPROVEN"),
            reasons=list(conf.get("reasons", []) or []),
            evidence_gaps=list(conf.get("evidence_gaps", []) or []),
        ),
        release_profiles=profiles,
        hard_dependencies=_dependencies(deps.get("hard")),
        soft_dependencies=_dependencies(deps.get("soft")),
        optional_dependencies=_dependencies(deps.get("optional")),
        operational_ownership=ownership,
        business_applicable=bool(biz.get("applicable", False)),
        business=_control_block({"controls": biz.get("controls"), "remaining_work": biz.get("remaining_work"), "denominator": biz.get("denominator", "")}),
        historical=dict(data.get("historical", {}) or {}),
        source_path=source_path,
    )


def load_features(root: Path = ROOT) -> list[FeatureRecord]:
    features_dir = root / "config" / "readiness" / "features"
    out: list[FeatureRecord] = []
    if not features_dir.exists():
        return out
    for path in sorted(features_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not data:
            continue
        out.append(feature_from_dict(data, source_path=str(path.relative_to(root))))
    return out


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
@dataclass
class ProfileEvaluation:
    profile: str
    participation: str
    implementation_floor: str
    disposition: str  # effective (accounts for hard dependencies)
    intrinsic_disposition: str  # the feature's own readiness, deps aside
    implementation_percent: float
    productionization_percent: float
    business_percent: float
    activation_state: str
    environment_gate: Optional[str]
    environment_state: str
    hard_blockers: list[str] = field(default_factory=list)
    external_blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _floor_for(feature: FeatureRecord, spec: ProfileSpec) -> str:
    part = feature.release_profiles.get(spec.id)
    floor = part.implementation_floor if part and part.implementation_floor else spec.implementation_floor
    return floor


def _prod_required_for(feature: FeatureRecord, spec: ProfileSpec) -> bool:
    part = feature.release_profiles.get(spec.id)
    if part and part.productionization_required is not None:
        return part.productionization_required
    return spec.productionization_required


def _env_gate_for(feature: FeatureRecord, spec: ProfileSpec) -> Optional[str]:
    part = feature.release_profiles.get(spec.id)
    if part and part.environment_gate is not None:
        return part.environment_gate
    return spec.environment_gate


def _business_gate_for(feature: FeatureRecord, spec: ProfileSpec) -> bool:
    part = feature.release_profiles.get(spec.id)
    if part and part.business_gate is not None:
        return part.business_gate
    return spec.business_gate


def _implementation_open(feature: FeatureRecord, floor: str) -> tuple[bool, list[str]]:
    """Return (has_open_repo_work, reasons)."""
    reasons: list[str] = []
    impl = feature.implementation
    if IMPLEMENTATION_RANK.get(impl.state, 0) < IMPLEMENTATION_RANK.get(floor, 0):
        reasons.append(
            f"implementation state {impl.state} is below the {floor} floor"
        )
    if impl.percent() < 100.0:
        reasons.append(
            f"implementation completion {impl.percent():g}% (< 100% of {impl.denominator or 'in-scope controls'})"
        )
    if impl.remaining_work:
        reasons.append("open repository work: " + "; ".join(impl.remaining_work))
    return (bool(reasons), reasons)


def _profile_external_blockers(feature: FeatureRecord, profile: str) -> list[Blocker]:
    out: list[Blocker] = []
    for b in feature.activation_blockers:
        if b.affected_release_profiles and profile not in b.affected_release_profiles:
            continue
        out.append(b)
    return out


def _unsatisfied_hard_deps(feature: FeatureRecord) -> list[Dependency]:
    out: list[Dependency] = []
    for d in feature.hard_dependencies:
        if d.state == "SATISFIED":
            continue
        # A hard dependency prevents release unless it explicitly only prevents
        # a narrower stage; default (no `prevents`) means it prevents release.
        if not d.prevents or "release" in d.prevents or "activation" in d.prevents:
            out.append(d)
    return out


def evaluate_profile(feature: FeatureRecord, spec: ProfileSpec, model: ReadinessModel) -> ProfileEvaluation:
    part = feature.release_profiles.get(spec.id)
    participation = part.participation if part else "not_in_release"
    floor = _floor_for(feature, spec)
    prod_required = _prod_required_for(feature, spec)
    env_gate = _env_gate_for(feature, spec)
    business_gate = _business_gate_for(feature, spec)

    impl_pct = feature.implementation.percent()
    prod_pct = feature.productionization.percent()
    biz_pct = feature.business.percent()

    env_state = "NOT_APPLICABLE"
    if env_gate:
        rec = feature.environment_evidence.get(env_gate)
        env_state = rec.state if rec else "NOT_ATTEMPTED"

    ev = ProfileEvaluation(
        profile=spec.id,
        participation=participation,
        implementation_floor=floor,
        disposition="NOT_IN_PROFILE",
        intrinsic_disposition="NOT_IN_PROFILE",
        implementation_percent=impl_pct,
        productionization_percent=prod_pct,
        business_percent=biz_pct,
        activation_state=feature.activation_state,
        environment_gate=env_gate,
        environment_state=env_state,
    )

    # Gate 0 — participation.
    if participation == "not_in_release":
        return ev
    if participation == "disabled_intentionally":
        ev.disposition = ev.intrinsic_disposition = "DISABLED_INTENTIONALLY"
        return ev

    external = _profile_external_blockers(feature, spec.id)
    for b in external:
        ev.external_blockers.append(f"{b.type}: {b.description} (owner: {b.owner})")

    # ---- intrinsic ladder (the feature's own readiness; dependencies aside) --
    intrinsic = _intrinsic_disposition(
        feature, spec, floor, prod_required, env_gate, env_state, business_gate, external, ev
    )
    ev.intrinsic_disposition = intrinsic

    # ---- effective ladder (adds hard-dependency gating) ----------------------
    effective = intrinsic
    unmet = _unsatisfied_hard_deps(feature)
    if unmet and intrinsic not in {"BLOCKED_BY_CODE"}:
        # A dependency never rewrites intrinsic implementation completion, but it
        # does gate effective release readiness.
        for d in unmet:
            ev.hard_blockers.append(
                f"hard dependency {d.feature_id} is {d.state}"
                + (f" ({d.note})" if d.note else "")
            )
        effective = "BLOCKED_BY_DEPENDENCY"
    ev.disposition = effective
    return ev


def _intrinsic_disposition(
    feature: FeatureRecord,
    spec: ProfileSpec,
    floor: str,
    prod_required: bool,
    env_gate: Optional[str],
    env_state: str,
    business_gate: bool,
    external: list[Blocker],
    ev: ProfileEvaluation,
) -> str:
    # Gate 1 — repository implementation.
    open_work, reasons = _implementation_open(feature, floor)
    if open_work:
        ev.hard_blockers.extend(reasons)
        ev.reasons.extend(reasons)
        return "BLOCKED_BY_CODE"

    # Gate 2 — productionization (technical operational controls).
    if prod_required and not feature.productionization.complete():
        msg = (
            f"productionization {feature.productionization.percent():g}% "
            f"(< 100% of {feature.productionization.denominator or 'in-scope controls'})"
        )
        if feature.productionization.remaining_work:
            msg += "; remaining: " + "; ".join(feature.productionization.remaining_work)
        ev.hard_blockers.append(msg)
        return "BLOCKED_BY_PRODUCTIONIZATION"

    # Implementation and productionization are complete. Determine external
    # activation vs environment evidence. External blocking is decided per
    # profile: only blockers that apply to THIS profile count (the global
    # activation_state is a summary, not the per-profile truth). An
    # ENVIRONMENT_VALIDATION_PENDING blocker is a "validate" condition, not an
    # "activate" one, so it flows to the environment-evidence branch below.
    has_external = any(
        (not b.source_code_change_expected) and b.type != "ENVIRONMENT_VALIDATION_PENDING"
        for b in external
    )

    # A gating environment blocked externally means the environment itself is
    # not yet reachable — that is an activation condition, not a validation one.
    if env_gate and env_state == "BLOCKED_EXTERNAL":
        has_external = True
        ev.reasons.append(f"{env_gate} environment blocked externally")

    if has_external:
        return "READY_TO_ACTIVATE"

    # Activation is clear. Now the environment evidence hard gate.
    if env_gate and env_state == "FAILED":
        rec = feature.environment_evidence.get(env_gate)
        summary = (rec.failure_summary if rec else None) or "no summary"
        ev.hard_blockers.append(
            f"{env_gate} evidence FAILED — {summary} (implementation unchanged; revalidation required)"
        )
        # A failed hard-gate environment blocks release. It is not a code
        # completeness fault; it is a failed technical/operational verification.
        return "BLOCKED_BY_PRODUCTIONIZATION"

    if env_gate and env_state in {"NOT_ATTEMPTED", "EXPIRED"}:
        if env_state == "EXPIRED":
            ev.warnings.append(f"{env_gate} evidence EXPIRED — revalidation required")
        return "READY_TO_VALIDATE"

    # env_state is VERIFIED or NOT_APPLICABLE (no gating env) — technical gates pass.
    # Business gate.
    if business_gate and feature.business_applicable and not feature.business.complete():
        ev.warnings.append(
            f"business readiness {feature.business.percent():g}% "
            f"(< 100% of {feature.business.denominator or 'in-scope controls'})"
        )
        return "BUSINESS_READINESS_PENDING"

    return _terminal_eligibility(feature, spec, env_gate, env_state, ev)


def _terminal_eligibility(
    feature: FeatureRecord,
    spec: ProfileSpec,
    env_gate: Optional[str],
    env_state: str,
    ev: ProfileEvaluation,
) -> str:
    """Map a fully technically+business-ready feature onto its profile tier."""
    # Production-scale: scale evidence verified => SCALE_VERIFIED.
    if spec.id == "production-scale":
        scale = feature.environment_evidence.get("scale")
        if scale and scale.state == "VERIFIED":
            return "SCALE_VERIFIED"
        return "PRODUCTION_ELIGIBLE"
    if spec.id == "production-lean":
        prod = feature.environment_evidence.get("production")
        if prod and prod.state == "VERIFIED":
            return "LIVE_VERIFIED"
        return "PRODUCTION_ELIGIBLE"
    if spec.id == "pilot":
        return "PILOT_ELIGIBLE"
    # local / staging and any other technical-only tier.
    return "TECHNICALLY_RELEASE_ELIGIBLE"


def evaluate_feature(feature: FeatureRecord, model: ReadinessModel) -> dict[str, ProfileEvaluation]:
    return {pid: evaluate_profile(feature, spec, model) for pid, spec in model.profiles.items()}


# ---------------------------------------------------------------------------
# Profile-level (aggregate) evaluation
# ---------------------------------------------------------------------------
@dataclass
class ProfileReport:
    profile: str
    title: str
    required_features: list[str]
    experimental_features: list[str]
    disposition: str
    coverage: dict[str, Any]
    feature_dispositions: dict[str, str]
    hard_blockers: list[str]
    external_blockers: list[str]
    warnings: list[str]


def evaluate_release_profile(profile_id: str, features: list[FeatureRecord], model: ReadinessModel) -> ProfileReport:
    spec = model.profiles[profile_id]
    required: list[str] = []
    experimental: list[str] = []
    feature_disp: dict[str, str] = {}
    hard_blockers: list[str] = []
    external_blockers: list[str] = []
    warnings: list[str] = []

    impl_ok = prod_ok = act_ok = env_ok = dep_ok = own_ok = biz_ok = 0
    impl_den = prod_den = act_den = env_den = dep_den = own_den = biz_den = 0

    for feat in features:
        ev = evaluate_profile(feat, spec, model)
        part = feat.release_profiles.get(profile_id)
        participation = part.participation if part else "not_in_release"
        if participation == "not_in_release":
            continue
        if participation == "disabled_intentionally":
            feature_disp[feat.feature_id] = "DISABLED_INTENTIONALLY"
            continue
        if participation == "experimental":
            experimental.append(feat.feature_id)
        else:
            required.append(feat.feature_id)
        feature_disp[feat.feature_id] = ev.disposition
        for b in ev.hard_blockers:
            hard_blockers.append(f"{feat.feature_id}: {b}")
        for b in ev.external_blockers:
            external_blockers.append(f"{feat.feature_id}: {b}")
        for w in ev.warnings:
            warnings.append(f"{feat.feature_id}: {w}")

        # Coverage is measured over required features only.
        if participation != "required":
            continue
        floor = _floor_for(feat, spec)
        prod_required = _prod_required_for(feat, spec)
        env_gate = _env_gate_for(feat, spec)
        business_gate = _business_gate_for(feat, spec)

        impl_den += 1
        if not _implementation_open(feat, floor)[0]:
            impl_ok += 1
        if prod_required:
            prod_den += 1
            if feat.productionization.complete():
                prod_ok += 1
        act_den += 1
        if feat.activation_state == "NO_EXTERNAL_BLOCKER":
            act_ok += 1
        if env_gate:
            env_den += 1
            rec = feat.environment_evidence.get(env_gate)
            if rec and rec.state == "VERIFIED":
                env_ok += 1
        dep_den += 1
        if not _unsatisfied_hard_deps(feat):
            dep_ok += 1
        own_den += 1
        if feat.operational_ownership.is_present():
            own_ok += 1
        if business_gate and feat.business_applicable:
            biz_den += 1
            if feat.business.complete():
                biz_ok += 1

    def pct(n: int, d: int) -> Optional[float]:
        return None if d == 0 else round(n / d * 100.0, 1)

    coverage = {
        "implementation": {"ok": impl_ok, "of": impl_den, "percent": pct(impl_ok, impl_den)},
        "productionization": {"ok": prod_ok, "of": prod_den, "percent": pct(prod_ok, prod_den)},
        "activation": {"ok": act_ok, "of": act_den, "percent": pct(act_ok, act_den)},
        "environment_evidence": {"ok": env_ok, "of": env_den, "percent": pct(env_ok, env_den)},
        "dependency_satisfaction": {"ok": dep_ok, "of": dep_den, "percent": pct(dep_ok, dep_den)},
        "operational_ownership": {"ok": own_ok, "of": own_den, "percent": pct(own_ok, own_den)},
        "business_readiness": {"ok": biz_ok, "of": biz_den, "percent": pct(biz_ok, biz_den)},
    }

    # The profile is only as ready as its weakest REQUIRED capability. Hard
    # gates decide this — never an average of the coverage percentages.
    disposition = _reduce_profile_disposition([feature_disp[f] for f in required])

    return ProfileReport(
        profile=profile_id,
        title=spec.title,
        required_features=sorted(required),
        experimental_features=sorted(experimental),
        disposition=disposition,
        coverage=coverage,
        feature_dispositions=feature_disp,
        hard_blockers=sorted(hard_blockers),
        external_blockers=sorted(external_blockers),
        warnings=sorted(warnings),
    )


def _reduce_profile_disposition(dispositions: list[str]) -> str:
    ranked = [d for d in dispositions if d in DISPOSITION_RANK]
    if not ranked:
        return "NOT_IN_PROFILE"
    return min(ranked, key=lambda d: DISPOSITION_RANK[d])


__all__ = [
    "ROOT",
    "FeatureRecord",
    "ReadinessModel",
    "ProfileSpec",
    "ProfileEvaluation",
    "ProfileReport",
    "load_model",
    "load_features",
    "feature_from_dict",
    "completion_percent",
    "evaluate_profile",
    "evaluate_feature",
    "evaluate_release_profile",
    "IMPLEMENTATION_STATES",
    "IMPLEMENTATION_RANK",
    "CEILINGS",
    "ACTIVATION_STATES",
    "ENVIRONMENT_STATES",
    "ENVIRONMENTS",
    "CONFIDENCE_LEVELS",
    "DISPOSITIONS",
]
