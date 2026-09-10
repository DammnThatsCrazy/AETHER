from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.delivery_contracts import (
    DeploymentImpact,
    FailureEnvelope,
    sanitize_detail,
    validate_release_candidate,
)


ROOT = Path(__file__).resolve().parents[2]


def test_deployment_impact_derives_rollback_and_approval_inputs():
    impact = DeploymentImpact.for_candidate(
        profile="staging",
        components=["backend", "frontend"],
        affected_domains=["backend"],
        migration_version="20260907_example",
        security_sensitive=True,
        approval_required=True,
    )
    value = impact.as_dict()
    assert value["migration_required"] is True
    assert value["rollback_required"] is True
    assert value["approval_required"] is True
    jsonschema.Draft202012Validator(
        json.loads((ROOT / "contracts/delivery/deployment-impact.schema.json").read_text())
    ).validate(value)


def test_failure_envelope_redacts_command_secrets_and_is_schema_valid():
    envelope = FailureEnvelope.from_result(
        operation_id="rc-1",
        stage="preflight",
        status="FAILED",
        code="COMMAND_FAILED",
        reason="Authorization: Bearer super-secret token=also-secret",
        evidence_ref="release-evidence/staging.json",
        retryable=False,
    ).as_dict()
    assert "super-secret" not in envelope["message"]
    assert "also-secret" not in envelope["message"]
    jsonschema.Draft202012Validator(
        json.loads((ROOT / "contracts/delivery/failure-envelope.schema.json").read_text())
    ).validate(envelope)


def test_failure_envelope_rejects_success_status():
    with pytest.raises(ValueError, match="BLOCKED or FAILED"):
        FailureEnvelope("op", "stage", "PASS", "bad", "reason", False, True)


def test_release_candidate_validation_requires_lock_digests_and_impact():
    errors = validate_release_candidate({"schema_version": 1})
    assert any("dependency_lock_digests" in error for error in errors)
    assert any("deployment_impact" in error for error in errors)


def test_sanitize_detail_bounds_large_output():
    assert len(sanitize_detail("x" * 5000)) == 4000
