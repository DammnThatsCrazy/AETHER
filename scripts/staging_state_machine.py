"""Resumable, fail-closed staging orchestration primitives.

This module contains no cloud client and performs no deployment mutation.  It
owns the durable checkpoint and the identity checks that must happen before a
workflow can resume an operation:

* a checkpoint is bound to one validated ``ReleaseCandidate``;
* each stage is checkpointed only after its command returns a passing result;
* a retry resumes at the first incomplete stage and never changes candidate
  identity; and
* promotion, rollback, and ephemeral cleanup evidence are checked as pure
  functions so GitHub Actions can call them without an AWS fixture.

The state file is evidence, not proof that a cloud deployment occurred.  The
executor is injected by ``scripts/delivery_orchestrator.py`` or a workflow.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from delivery_contracts import FailureEnvelope, sanitize_detail, validate_release_candidate
except ModuleNotFoundError:  # pragma: no cover - import-mode compatibility
    from scripts.delivery_contracts import FailureEnvelope, sanitize_detail, validate_release_candidate


SCHEMA_VERSION = 1
COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EPHEMERAL_PROFILES = frozenset({"demo", "preview"})
STAGES = (
    "aws_identity",
    "preflight",
    "deploy",
    "migration",
    "tenant_activation",
    "golden_journeys",
)
PASSING_STAGE_STATUSES = frozenset({"PASS", "NOT_APPLICABLE", "PASS_WITH_DEGRADATION"})
STAGE_STATUSES = PASSING_STAGE_STATUSES | frozenset({"BLOCKED", "FAILED"})


class StateMachineError(ValueError):
    """Raised when a checkpoint or evidence record is unsafe to consume."""


@dataclass(frozen=True)
class CandidateIdentity:
    """The exact identity that promotion and rollback evidence must carry."""

    release_candidate_id: str
    commit_sha: str
    artifact_digest: str
    profile: str

    def as_dict(self) -> dict[str, str]:
        return {
            "release_candidate_id": self.release_candidate_id,
            "commit_sha": self.commit_sha,
            "artifact_digest": self.artifact_digest,
            "profile": self.profile,
        }


def _require_identity_fields(value: Mapping[str, Any], *, label: str) -> CandidateIdentity:
    missing = [name for name in CandidateIdentity.__dataclass_fields__ if not value.get(name)]
    if missing:
        raise StateMachineError(f"{label} is missing identity fields: {', '.join(missing)}")
    commit = str(value["commit_sha"])
    digest = str(value["artifact_digest"])
    if not COMMIT_RE.fullmatch(commit):
        raise StateMachineError(f"{label}.commit_sha is not a lowercase git SHA")
    if not DIGEST_RE.fullmatch(digest):
        raise StateMachineError(f"{label}.artifact_digest is not an immutable sha256 digest")
    return CandidateIdentity(
        release_candidate_id=str(value["release_candidate_id"]),
        commit_sha=commit,
        artifact_digest=digest,
        profile=str(value["profile"]),
    )


def candidate_identity(candidate: Mapping[str, Any], profile: str | None = None) -> CandidateIdentity:
    """Validate a ReleaseCandidate and derive its immutable execution identity."""

    errors = validate_release_candidate(candidate)
    if errors:
        raise StateMachineError("invalid release candidate: " + "; ".join(errors))
    profiles = candidate.get("deployment_profiles") or []
    if not isinstance(profiles, list) or not profiles:
        raise StateMachineError("candidate deployment_profiles must contain at least one profile")
    selected_profile = profile or str(profiles[0])
    if selected_profile not in profiles:
        raise StateMachineError(
            f"candidate {candidate['release_candidate_id']} is not compatible with {selected_profile}"
        )
    impact = candidate.get("deployment_impact") or {}
    if impact.get("profile") != selected_profile:
        raise StateMachineError("candidate deployment impact profile does not match execution profile")
    return _require_identity_fields(
        {
            "release_candidate_id": candidate.get("release_candidate_id"),
            "commit_sha": candidate.get("commit_sha"),
            "artifact_digest": candidate.get("artifact_digest"),
            "profile": selected_profile,
        },
        label="candidate",
    )


def _record_identity(record: Mapping[str, Any], *, label: str) -> CandidateIdentity:
    for key in ("candidate_identity", "candidate", "identity"):
        nested = record.get(key)
        if isinstance(nested, Mapping):
            return _require_identity_fields(nested, label=f"{label}.{key}")
    return _require_identity_fields(record, label=label)


def _assert_same(expected: CandidateIdentity, actual: CandidateIdentity, *, label: str) -> None:
    if expected != actual:
        differences = [
            field
            for field in CandidateIdentity.__dataclass_fields__
            if getattr(expected, field) != getattr(actual, field)
        ]
        raise StateMachineError(f"{label} does not match exact candidate identity: {', '.join(differences)}")


def verify_promotion_identity(
    candidate: Mapping[str, Any], promotion: Mapping[str, Any], profile: str | None = None
) -> CandidateIdentity:
    """Verify that a promotion record names exactly the supplied candidate.

    The caller may wrap identity under ``candidate_identity`` or ``candidate``;
    accepting both lets existing workflow result envelopes participate without
    weakening the four-field equality check.
    """

    expected = candidate_identity(candidate, profile)
    actual = _record_identity(promotion, label="promotion")
    _assert_same(expected, actual, label="promotion")
    status = str(promotion.get("status", "")).upper()
    if status not in {"PASS", "PROMOTED", "DEPLOYED", "COMPLETE"}:
        raise StateMachineError(f"promotion status {status or '<missing>'} is not a successful promotion")
    return expected


def verify_rollback_identity(
    promoted_candidate: Mapping[str, Any],
    rollback_target: Mapping[str, Any],
    rollback: Mapping[str, Any],
    profile: str | None = None,
) -> tuple[CandidateIdentity, CandidateIdentity]:
    """Verify both sides of a rollback: promoted source and exact stable target."""

    source = candidate_identity(promoted_candidate, profile)
    target = candidate_identity(rollback_target, profile)
    actual_source = rollback.get("from_candidate") or rollback.get("source")
    actual_target = rollback.get("to_candidate") or rollback.get("target")
    if not isinstance(actual_source, Mapping) or not isinstance(actual_target, Mapping):
        raise StateMachineError("rollback must include from_candidate and to_candidate identities")
    _assert_same(source, _record_identity(actual_source, label="rollback.from_candidate"), label="rollback source")
    _assert_same(target, _record_identity(actual_target, label="rollback.to_candidate"), label="rollback target")
    status = str(rollback.get("status", "")).upper()
    if status not in {"PASS", "ROLLED_BACK", "COMPLETE"}:
        raise StateMachineError(f"rollback status {status or '<missing>'} is not a successful rollback")
    if source == target:
        raise StateMachineError("rollback source and target must be different candidates")
    return source, target


def validate_ephemeral_cleanup_contract(
    profile: str,
    env: str,
    profile_config: Mapping[str, Any],
    workflow_pairs: list[tuple[str, str]] | set[tuple[str, str]],
    lease_value: Any,
    now: datetime,
) -> dict[str, Any]:
    """Validate ephemeral cleanup policy and an injected TTL lease offline.

    ``lease_value`` is intentionally injected.  ``None`` or malformed input is
    a blocked cleanup contract, matching the fail-closed behavior of the
    repository's ``ephemeral_ttl_guard`` without contacting AWS.
    """

    if profile not in EPHEMERAL_PROFILES:
        return {
            "status": "NOT_APPLICABLE",
            "required": False,
            "profile": profile,
            "env": env,
            "lease_path": None,
            "reason": "profile is not ephemeral",
        }
    from scripts.release.ephemeral_ttl_guard import evaluate, lease_path

    path = lease_path(profile, env)
    errors: list[str] = []
    if profile_config.get("class") != profile:
        errors.append(f"profile class is not {profile}")
    if profile_config.get("ttl_cleanup_required") is not True:
        errors.append("ttl_cleanup_required must be true")
    if (profile, env) not in set(workflow_pairs):
        errors.append("ephemeral TTL workflow matrix does not cover this profile/env")
    decision = evaluate(profile, env, lambda _profile, _env: lease_value, now)
    if decision["expired"]:
        errors.append(decision["reason"] or "lease is expired")
    return {
        "status": "BLOCKED" if errors else "PASS",
        "required": True,
        "profile": profile,
        "env": env,
        "lease_path": path,
        "expires_at": decision.get("expires_at").isoformat() if decision.get("expires_at") else None,
        "reason": "; ".join(errors) if errors else "ephemeral cleanup and live TTL contract verified",
    }


def validate_environment_resolution(resolution: Mapping[str, Any], profile: str) -> dict[str, Any]:
    """Validate a pre-mutation environment-resolution decision for a profile."""

    if not isinstance(resolution, Mapping):
        raise StateMachineError("environment resolution must be an object")
    required = {"schema_version", "requested_profile", "resolved_profile", "capabilities", "omitted", "promotion_equivalence", "production_equivalent", "disposition", "blockers"}
    missing = sorted(required - set(resolution))
    if missing:
        raise StateMachineError("environment resolution is missing fields: " + ", ".join(missing))
    if resolution.get("schema_version") != 1:
        raise StateMachineError("environment resolution schema_version must be 1")
    if resolution.get("requested_profile") != profile:
        raise StateMachineError("environment resolution requested_profile does not match execution profile")
    if resolution.get("disposition") not in {"PASS", "PASS_WITH_DEGRADATION", "BLOCKED_EXTERNAL"}:
        raise StateMachineError("environment resolution disposition is invalid")
    if not isinstance(resolution.get("capabilities"), Mapping) or not isinstance(resolution.get("omitted"), list) or not isinstance(resolution.get("blockers"), list):
        raise StateMachineError("environment resolution capabilities, omitted, and blockers have invalid shapes")
    if resolution.get("disposition") == "BLOCKED_EXTERNAL":
        raise StateMachineError("environment resolution is BLOCKED_EXTERNAL")
    # PASS evidence is a promotion input, so it must be reproducible from the
    # canonical profile requirements.  A hand-edited/stale envelope must not
    # turn an unavailable capability into a mutation authorization.  Older
    # degraded envelopes may intentionally contain only the capability that
    # triggered degradation; retain their shape compatibility, but never grant
    # that compatibility to PASS evidence.
    capabilities = resolution["capabilities"]
    if any(
        not isinstance(name, str)
        or not isinstance(entry, Mapping)
        or entry.get("status") not in {"PASS", "UNAVAILABLE", "BLOCKED", "UNKNOWN"}
        or not isinstance(entry.get("required"), bool)
        for name, entry in capabilities.items()
    ):
        raise StateMachineError("environment resolution capabilities contain malformed evidence")
    try:
        from scripts.release.resolve_environment import load_requirements, resolve
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from release.resolve_environment import load_requirements, resolve

    try:
        requirements = load_requirements()
        spec = requirements["profiles"][profile]
        canonical_names = set(spec.get("required", [])) | set(spec.get("optional", []))
        observed = {name: entry["status"] for name, entry in capabilities.items()}
        if resolution.get("disposition") == "PASS" and set(observed) != canonical_names:
            missing_caps = sorted(canonical_names - set(observed))
            extra_caps = sorted(set(observed) - canonical_names)
            details = []
            if missing_caps:
                details.append("missing capabilities: " + ", ".join(missing_caps))
            if extra_caps:
                details.append("unknown capabilities: " + ", ".join(extra_caps))
            raise StateMachineError("PASS environment resolution is incomplete: " + "; ".join(details))
        recomputed = resolve(profile, observed, requirements=requirements)
    except (KeyError, TypeError, ValueError) as exc:
        raise StateMachineError(f"cannot recompute environment resolution: {exc}") from exc
    if resolution.get("disposition") == "PASS":
        for field in ("resolved_profile", "promotion_equivalence", "production_equivalent", "disposition", "blockers", "omitted"):
            if resolution.get(field) != recomputed.get(field):
                raise StateMachineError(f"environment resolution {field} is stale or inconsistent with canonical requirements")
        if dict(capabilities) != recomputed.get("capabilities"):
            raise StateMachineError("environment resolution capabilities are stale or inconsistent with canonical requirements")
    else:
        # Degraded evidence is still a complete canonical capability record. A
        # missing capability must remain UNKNOWN rather than being omitted,
        # and only the profile's explicit degradable set may explain a
        # non-PASS entry. This keeps degraded evidence reproducible and
        # prevents a sparse envelope from hiding an unrelated blocker.
        canonical_names = set(spec.get("required", [])) | set(spec.get("optional", []))
        if set(capabilities) != canonical_names:
            missing_caps = sorted(canonical_names - set(capabilities))
            extra_caps = sorted(set(capabilities) - canonical_names)
            details = []
            if missing_caps:
                details.append("missing capabilities: " + ", ".join(missing_caps))
            if extra_caps:
                details.append("unknown capabilities: " + ", ".join(extra_caps))
            raise StateMachineError("degraded environment resolution is incomplete: " + "; ".join(details))
        recomputed = resolve(profile, {name: entry["status"] for name, entry in capabilities.items()}, requirements=requirements)
        if any(
            capabilities[name].get("status") != entry.get("status")
            or capabilities[name].get("required") != entry.get("required")
            for name, entry in recomputed.get("capabilities", {}).items()
        ):
            raise StateMachineError("degraded environment resolution capabilities are stale or inconsistent with canonical requirements")
        omitted_shape = {(item.get("capability"), item.get("impact")) for item in resolution.get("omitted", []) if isinstance(item, Mapping)}
        recomputed_omitted_shape = {(item.get("capability"), item.get("impact")) for item in recomputed.get("omitted", []) if isinstance(item, Mapping)}
        if omitted_shape != recomputed_omitted_shape:
            raise StateMachineError("degraded environment resolution omitted entries are stale or inconsistent with canonical requirements")
        if resolution.get("promotion_equivalence") != recomputed.get("promotion_equivalence"):
            raise StateMachineError("degraded environment resolution promotion equivalence is stale or inconsistent with canonical requirements")
        degradable = set(spec.get("degradable", []))
        if resolution.get("resolved_profile") != f"{profile}-degraded":
            raise StateMachineError("degraded environment resolution has an invalid resolved_profile")
        if resolution.get("production_equivalent") is not False:
            raise StateMachineError("degraded environment resolution cannot be production equivalent")
        if resolution.get("blockers"):
            raise StateMachineError("degraded environment resolution cannot contain blockers")
        omitted = resolution.get("omitted") or []
        if not omitted:
            raise StateMachineError("degraded environment resolution must name an omitted capability")
        omitted_names: set[str] = set()
        for item in omitted:
            if not isinstance(item, Mapping) or not isinstance(item.get("capability"), str):
                raise StateMachineError("environment resolution omitted entries are malformed")
            name = item["capability"]
            omitted_names.add(name)
            optional = set(spec.get("optional", []))
            if item.get("impact") == "DEGRADED" and name in degradable:
                continue
            if item.get("impact") == "OPTIONAL" and name in optional:
                continue
            if item.get("impact") != "DEGRADED" or name not in degradable:
                raise StateMachineError("degraded environment resolution names a non-degradable capability")
        for name, entry in capabilities.items():
            if entry["status"] != "PASS" and name not in omitted_names:
                raise StateMachineError("degraded environment resolution omits a non-passing capability")
    return dict(resolution)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


class StagingStateMachine:
    """Persisted stage runner that can safely resume after a failed attempt."""

    def __init__(self, state_path: Path, state: dict[str, Any]) -> None:
        self.state_path = state_path
        self.state = state

    @classmethod
    def open(
        cls,
        state_path: Path,
        candidate: Mapping[str, Any],
        profile: str,
        *,
        operation_id: str | None = None,
        cleanup: Mapping[str, Any] | None = None,
        environment_resolution: Mapping[str, Any] | None = None,
    ) -> "StagingStateMachine":
        identity = candidate_identity(candidate, profile)
        validated_resolution = (
            validate_environment_resolution(environment_resolution, profile)
            if environment_resolution is not None else None
        )
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StateMachineError(f"cannot read staging checkpoint: {exc}") from exc
            cls._validate_state(state)
            stored = _require_identity_fields(state["candidate_identity"], label="checkpoint.candidate_identity")
            _assert_same(identity, stored, label="checkpoint")
            if state["profile"] != profile:
                raise StateMachineError("checkpoint profile does not match requested profile")
            stored_resolution = state.get("environment_resolution")
            if stored_resolution and validated_resolution is None and stored_resolution.get("disposition") == "BLOCKED_EXTERNAL":
                raise StateMachineError("checkpoint has a blocked environment resolution; fresh resolution evidence is required")
            if validated_resolution is not None:
                state["environment_resolution"] = validated_resolution
            cleanup_state = state.get("ephemeral_cleanup") or {}
            if cleanup_state.get("status") == "BLOCKED" and cleanup is None:
                raise StateMachineError("checkpoint has a blocked ephemeral cleanup contract; fresh cleanup evidence is required")
            cleanup_updated = cleanup is not None
            resolution_updated = validated_resolution is not None
            if cleanup_updated:
                state["ephemeral_cleanup"] = dict(cleanup)
                if cleanup.get("status") == "BLOCKED":
                    raise StateMachineError("ephemeral cleanup contract is still blocked")
            if state["status"] in {"BLOCKED", "FAILED"}:
                state["status"] = "RUNNING"
                state["resume_count"] = int(state.get("resume_count", 0)) + 1
                state["updated_at"] = _now()
                _atomic_write(state_path, state)
            elif cleanup_updated:
                state["updated_at"] = _now()
                _atomic_write(state_path, state)
            elif resolution_updated:
                state["updated_at"] = _now()
                _atomic_write(state_path, state)
            return cls(state_path, state)
        state = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": operation_id or f"staging-{identity.release_candidate_id}",
            "profile": profile,
            "candidate_identity": identity.as_dict(),
            "phase": STAGES[0],
            "status": "RUNNING",
            "completed_stages": [],
            "checks": [],
            "failures": [],
            "resume_count": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        if cleanup is not None:
            state["ephemeral_cleanup"] = dict(cleanup)
            if cleanup.get("status") == "BLOCKED":
                failure = FailureEnvelope.from_result(
                    operation_id=state["operation_id"],
                    stage="cleanup",
                    status="BLOCKED",
                    code="EPHEMERAL_CLEANUP_CONTRACT_INVALID",
                    reason=str(cleanup.get("reason") or "ephemeral cleanup contract is invalid"),
                    evidence_ref=str(state_path),
                    retryable=False,
                ).as_dict()
                state["failures"].append(failure)
                state["status"] = "BLOCKED"
        if validated_resolution is not None:
            state["environment_resolution"] = validated_resolution
            if validated_resolution["disposition"] == "PASS_WITH_DEGRADATION":
                state["checks"].append({
                    "check_id": "environment_resolution",
                    "status": "PASS_WITH_DEGRADATION",
                    "reason": "environment resolved with explicit degradation",
                })
        cls._validate_state(state)
        _atomic_write(state_path, state)
        return cls(state_path, state)

    @staticmethod
    def _validate_state(state: Mapping[str, Any]) -> None:
        required = {
            "schema_version", "operation_id", "profile", "candidate_identity", "phase",
            "status", "completed_stages", "checks", "failures", "resume_count", "created_at", "updated_at",
        }
        missing = sorted(required - set(state))
        if missing:
            raise StateMachineError("checkpoint missing fields: " + ", ".join(missing))
        if state.get("schema_version") != SCHEMA_VERSION:
            raise StateMachineError("checkpoint schema_version must be 1")
        if not str(state.get("operation_id", "")).strip() or not str(state.get("profile", "")).strip():
            raise StateMachineError("checkpoint operation_id and profile are required")
        if state.get("phase") not in (*STAGES, "complete"):
            raise StateMachineError("checkpoint phase is not a legal staging phase")
        if state.get("status") not in {"RUNNING", "BLOCKED", "FAILED", "COMPLETE"}:
            raise StateMachineError("checkpoint status is not a legal staging status")
        completed = state.get("completed_stages")
        if not isinstance(completed, list) or len(completed) != len(set(completed)) or any(stage not in STAGES for stage in completed):
            raise StateMachineError("checkpoint completed_stages is invalid")
        if completed != [stage for stage in STAGES if stage in completed]:
            raise StateMachineError("checkpoint completed_stages must preserve stage order")
        expected_phase = next((stage for stage in STAGES if stage not in completed), "complete")
        if state.get("phase") != expected_phase:
            raise StateMachineError("checkpoint phase does not match completed_stages")
        checks = state.get("checks")
        if not isinstance(checks, list):
            raise StateMachineError("checkpoint checks must be a list")
        for check in checks:
            if not isinstance(check, Mapping) or not str(check.get("check_id", "")).strip() or check.get("status") not in STAGE_STATUSES:
                raise StateMachineError("checkpoint contains an invalid stage check")
        failures = state.get("failures")
        if not isinstance(failures, list):
            raise StateMachineError("checkpoint failures must be a list")
        for failure in failures:
            if not isinstance(failure, Mapping) or failure.get("status") not in {"BLOCKED", "FAILED"} or failure.get("blocking") is not True:
                raise StateMachineError("checkpoint contains an invalid failure envelope")
        if state.get("environment_resolution") is not None:
            validate_environment_resolution(state["environment_resolution"], str(state["profile"]))
        _require_identity_fields(state.get("candidate_identity") or {}, label="checkpoint.candidate_identity")

    @property
    def next_stage(self) -> str | None:
        return next((stage for stage in STAGES if stage not in self.state["completed_stages"]), None)

    def record(self, stage: str, status: str, reason: str, *, evidence_ref: str | None = None) -> None:
        if stage not in STAGES:
            raise StateMachineError(f"unknown staging stage: {stage}")
        if status not in STAGE_STATUSES:
            raise StateMachineError(f"unknown staging stage status: {status}")
        expected = self.next_stage
        if expected != stage and stage not in self.state["completed_stages"]:
            raise StateMachineError(f"stage {stage} is out of order; next stage is {expected}")
        check = {"check_id": stage, "status": status, "reason": sanitize_detail(reason)}
        if stage in self.state["completed_stages"]:
            return
        self.state["checks"].append(check)
        if status in PASSING_STAGE_STATUSES:
            self.state["completed_stages"].append(stage)
            self.state["phase"] = self.next_stage or "complete"
            self.state["status"] = "COMPLETE" if self.next_stage is None else "RUNNING"
        else:
            failure = FailureEnvelope.from_result(
                operation_id=self.state["operation_id"],
                stage=stage,
                status=status,
                code="STAGE_BLOCKED" if status == "BLOCKED" else "STAGE_FAILED",
                reason=reason,
                evidence_ref=evidence_ref or str(self.state_path),
            ).as_dict()
            self.state["failures"].append(failure)
            self.state["status"] = status
        self.state["updated_at"] = _now()
        self._save()

    def run(self, execute: Callable[[str], tuple[str, str]], *, dry_run: bool = False) -> dict[str, Any]:
        """Execute remaining stages, checkpointing each result immediately."""
        if self.state["status"] in {"BLOCKED", "FAILED"}:
            return self.state
        if dry_run:
            for stage in STAGES:
                if stage not in self.state["completed_stages"]:
                    # NOT_APPLICABLE is evidence that execution was skipped,
                    # not evidence that the stage passed.  In particular do
                    # not use record(), whose contract advances checkpoints.
                    self.state["checks"].append({
                        "check_id": stage,
                        "status": "NOT_APPLICABLE",
                        "reason": "dry-run; command not executed",
                    })
            self.state["status"] = "RUNNING"
            self.state["phase"] = self.next_stage or "complete"
            self.state["updated_at"] = _now()
            self._save()
            return self.state
        while self.next_stage is not None:
            stage = self.next_stage
            try:
                status, reason = execute(stage)
            except Exception as exc:  # injected executors must fail closed too
                status, reason = "FAILED", f"stage executor raised: {exc}"
            self.record(stage, status, reason)
            if status not in PASSING_STAGE_STATUSES:
                break
        return self.state

    def _save(self) -> None:
        self._validate_state(self.state)
        _atomic_write(self.state_path, self.state)


__all__ = [
    "CandidateIdentity",
    "StateMachineError",
    "STAGES",
    "StagingStateMachine",
    "candidate_identity",
    "validate_environment_resolution",
    "validate_ephemeral_cleanup_contract",
    "verify_promotion_identity",
    "verify_rollback_identity",
]
