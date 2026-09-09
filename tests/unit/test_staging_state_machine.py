from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from scripts.artifact_builder import aggregate_digest
from scripts.delivery_contracts import DeploymentImpact
from scripts.staging_state_machine import (
    StateMachineError,
    StagingStateMachine,
    validate_ephemeral_cleanup_contract,
    validate_environment_resolution,
    verify_promotion_identity,
    verify_rollback_identity,
)


ROOT = Path(__file__).resolve().parents[2]


def candidate(candidate_id: str = "rc-state", *, profile: str = "staging", commit: str = "a" * 40, digest_letter: str = "a") -> dict:
    digest = "sha256:" + digest_letter * 64
    component_digests = {"repository-build": digest}
    return {
        "schema_version": 1,
        "release_candidate_id": candidate_id,
        "commit_sha": commit,
        "artifact_digest": aggregate_digest(component_digests),
        "dependency_lock_hash": aggregate_digest({}),
        "dependency_lock_digests": {},
        "contract_versions": {},
        "migration_version": "none",
        "model_versions": {},
        "policy_versions": {},
        "deployment_profiles": [profile],
        "affected_domains": ["delivery"],
        "required_checks": ["canonical-consistency"],
        "component_digests": component_digests,
        "deployment_impact": DeploymentImpact.for_candidate(
            profile=profile,
            components=["repository-build"],
            affected_domains=["delivery"],
            migration_version="none",
        ).as_dict(),
        "created_at": "2026-09-07T00:00:00+00:00",
    }


def test_checkpoint_is_schema_valid_and_resumes_at_first_incomplete_stage(tmp_path: Path):
    rc = candidate()
    state_path = tmp_path / "staging-state.json"
    machine = StagingStateMachine.open(state_path, rc, "staging")

    first_attempt = iter(
        [
            ("PASS", "identity resolved"),
            ("PASS", "preflight passed"),
            ("BLOCKED", "deploy command is unavailable"),
        ]
    )
    machine.run(lambda _stage: next(first_attempt))
    failed_state = json.loads(state_path.read_text())
    assert failed_state["completed_stages"] == ["aws_identity", "preflight"]
    assert failed_state["phase"] == "deploy"
    assert failed_state["status"] == "BLOCKED"
    assert failed_state["failures"][-1]["code"] == "STAGE_BLOCKED"

    resumed = StagingStateMachine.open(state_path, rc, "staging")
    observed: list[str] = []
    resumed.run(lambda stage: (observed.append(stage) or ("PASS", f"{stage} passed")))
    final_state = json.loads(state_path.read_text())
    assert observed == ["deploy", "migration", "tenant_activation", "golden_journeys"]
    assert final_state["status"] == "COMPLETE"
    assert final_state["phase"] == "complete"
    assert final_state["resume_count"] == 1
    jsonschema.Draft202012Validator(
        json.loads((ROOT / "contracts/delivery/staging-orchestration-state.schema.json").read_text()),
        format_checker=jsonschema.FormatChecker(),
    ).validate(final_state)


def test_checkpoint_refuses_a_different_candidate_or_profile(tmp_path: Path):
    state_path = tmp_path / "state.json"
    rc = candidate()
    StagingStateMachine.open(state_path, rc, "staging")
    with pytest.raises(StateMachineError, match="exact candidate identity"):
        StagingStateMachine.open(state_path, candidate(digest_letter="c"), "staging")
    with pytest.raises(StateMachineError, match="not compatible"):
        StagingStateMachine.open(tmp_path / "other.json", rc, "production-lean")


def test_checkpoint_binds_environment_resolution_and_rejects_blocked_input(tmp_path: Path):
    resolution = {
        "schema_version": 1,
        "requested_profile": "staging",
        "resolved_profile": "staging-degraded",
        "capabilities": {"aurora": {"status": "UNAVAILABLE", "required": True}},
        "omitted": [{"capability": "aurora", "reason": "unavailable", "impact": "DEGRADED"}],
        "promotion_equivalence": "production-lean",
        "production_equivalent": False,
        "disposition": "PASS_WITH_DEGRADATION",
        "blockers": [],
    }
    state_path = tmp_path / "state.json"
    machine = StagingStateMachine.open(state_path, candidate(), "staging", environment_resolution=resolution)
    assert machine.state["environment_resolution"]["disposition"] == "PASS_WITH_DEGRADATION"
    assert machine.state["checks"][0]["check_id"] == "environment_resolution"
    blocked = dict(resolution, disposition="BLOCKED_EXTERNAL", blockers=["aurora: UNAVAILABLE"])
    with pytest.raises(StateMachineError, match="BLOCKED_EXTERNAL"):
        validate_environment_resolution(blocked, "staging")


def test_promotion_requires_exact_candidate_identity():
    rc = candidate()
    promotion = {
        "status": "PROMOTED",
        "candidate_identity": {
            "release_candidate_id": "rc-state",
            "commit_sha": "a" * 40,
            "artifact_digest": rc["artifact_digest"],
            "profile": "staging",
        },
        "plan_run_id": "123",
        "plan_checksum": "sha256:" + "c" * 64,
    }
    assert verify_promotion_identity(rc, promotion).release_candidate_id == "rc-state"
    promotion["candidate_identity"]["commit_sha"] = "d" * 40
    with pytest.raises(StateMachineError, match="commit_sha"):
        verify_promotion_identity(rc, promotion)


def test_rollback_requires_exact_source_and_stable_target():
    promoted = candidate("rc-new", commit="a" * 40, digest_letter="a")
    stable = candidate("rc-stable", commit="b" * 40, digest_letter="b")
    rollback = {
        "status": "ROLLED_BACK",
        "from_candidate": {
            "release_candidate_id": "rc-new",
            "commit_sha": "a" * 40,
            "artifact_digest": promoted["artifact_digest"],
            "profile": "staging",
        },
        "to_candidate": {
            "release_candidate_id": "rc-stable",
            "commit_sha": "b" * 40,
            "artifact_digest": stable["artifact_digest"],
            "profile": "staging",
        },
    }
    source, target = verify_rollback_identity(promoted, stable, rollback)
    assert (source.release_candidate_id, target.release_candidate_id) == ("rc-new", "rc-stable")
    rollback["to_candidate"]["artifact_digest"] = "sha256:" + "c" * 64
    with pytest.raises(StateMachineError, match="artifact_digest"):
        verify_rollback_identity(promoted, stable, rollback)


def test_ephemeral_cleanup_contract_is_fail_closed_and_offline():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    config = {"class": "preview", "ttl_cleanup_required": True}
    pairs = {("demo", "demo"), ("preview", "preview")}
    live = validate_ephemeral_cleanup_contract(
        "preview", "preview", config, pairs, "2026-09-07T02:00:00Z", now
    )
    assert live["status"] == "PASS"
    assert live["lease_path"] == "/aether/preview/preview/lifecycle/expires-at"
    missing = validate_ephemeral_cleanup_contract("preview", "preview", config, pairs, None, now)
    assert missing["status"] == "BLOCKED"
    assert "lease" in missing["reason"]
    not_applicable = validate_ephemeral_cleanup_contract("staging", "staging", {}, pairs, None, now)
    assert not_applicable["status"] == "NOT_APPLICABLE"


def test_ephemeral_cleanup_contract_rejects_policy_or_matrix_drift():
    now = datetime.now(timezone.utc)
    result = validate_ephemeral_cleanup_contract(
        "demo", "pr-42", {"class": "demo", "ttl_cleanup_required": False}, {("demo", "demo")},
        "2099-01-01T00:00:00Z", now,
    )
    assert result["status"] == "BLOCKED"
    assert "ttl_cleanup_required" in result["reason"]
    assert "matrix" in result["reason"]


def test_checkpoint_cannot_resume_with_stale_blocked_ephemeral_cleanup(tmp_path: Path):
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    cleanup = validate_ephemeral_cleanup_contract(
        "demo", "demo", {"class": "demo", "ttl_cleanup_required": True}, {("demo", "demo")}, None, now
    )
    state_path = tmp_path / "ephemeral-state.json"
    rc = candidate(profile="demo")
    machine = StagingStateMachine.open(state_path, rc, "demo", cleanup=cleanup)
    assert machine.state["status"] == "BLOCKED"
    with pytest.raises(StateMachineError, match="fresh cleanup evidence"):
        StagingStateMachine.open(state_path, rc, "demo")
