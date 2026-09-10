from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import jsonschema
import pytest

from scripts.artifact_builder import aggregate_digest
from scripts.release.artifact_closure import ArtifactClosureError, ArtifactSpec, validate_closure_evidence, verify_closure
from scripts.release.hosted_delivery_adapters import HostedAdapterError, validate_adapter_pair
from scripts.release.profile_delivery_contracts import DeliveryRequest, operation_telemetry, validate_result

ROOT = Path(__file__).resolve().parents[2]


def identity(profile: str = "staging") -> dict[str, str]:
    digest = "sha256:" + "a" * 64
    return {"release_candidate_id": "rc-hosted", "commit_sha": "a" * 40, "artifact_digest": digest, "profile": profile}


def candidate(profile: str = "staging", component_digest: str | None = None) -> dict:
    component_digest = component_digest or "sha256:" + "b" * 64
    return {
        "schema_version": 1,
        "release_candidate_id": "rc-hosted",
        "commit_sha": "a" * 40,
        "artifact_digest": aggregate_digest({"backend": component_digest}),
        "dependency_lock_hash": aggregate_digest({}),
        "dependency_lock_digests": {},
        "contract_versions": {},
        "migration_version": "none",
        "model_versions": {},
        "policy_versions": {},
        "deployment_profiles": [profile],
        "affected_domains": ["delivery"],
        "required_checks": ["canonical-consistency"],
        "component_digests": {"backend": component_digest},
        "deployment_impact": {
            "schema_version": 1,
            "profile": profile,
            "affected_domains": ["delivery"],
            "affected_components": ["backend"],
            "migration_required": False,
            "data_contract_change": False,
            "security_sensitive": False,
            "rollback_required": False,
            "approval_required": False,
            "risk_level": "medium",
            "rationale": "offline closure fixture",
        },
        "created_at": "2026-09-09T00:00:00+00:00",
    }


def request(profile: str = "staging", operation: str = "validate", **extra) -> DeliveryRequest:
    value = {
        "operation_id": "op-hosted",
        "operation": operation,
        "profile": profile,
        "candidate_identity": identity(profile),
        "requested_at": "2026-09-09T00:00:00Z",
        "dry_run": True,
        **extra,
    }
    return DeliveryRequest.from_mapping(value)


def test_hosted_adapter_requires_non_secret_credential_reference():
    valid = {
        "operation_id": "op-1", "authority": "environment", "profile": "staging", "read_only": True,
        "credential": {"provider": "aws", "source": "github_oidc", "role_arn": "arn:aws:iam::123456789012:role/read", "scopes": ["sts:GetCallerIdentity"]},
    }
    result = {
        "operation_id": "op-1", "authority": "environment", "profile": "staging", "status": "PASS",
        "source": "aws_read_only", "mutation_occurred": False, "retryable": False, "payload": {},
    }
    assert validate_adapter_pair(valid, result) == []
    valid["credential"]["secret_key"] = "plaintext"
    assert any("plaintext secret" in error for error in validate_adapter_pair(valid, result))


def test_fixture_cannot_claim_live_hosted_pass():
    req = {"operation_id": "op-1", "authority": "environment", "profile": "staging", "read_only": True,
           "credential": {"provider": "aws", "source": "github_oidc", "scopes": []}}
    result = {"operation_id": "op-1", "authority": "environment", "profile": "staging", "status": "PASS",
              "source": "offline_fixture", "mutation_occurred": False, "retryable": False, "payload": {}}
    assert any("cannot claim live" in error for error in validate_adapter_pair(req, result))


def test_direct_contract_constructors_fail_closed_on_schema_and_shape():
    assert any("schema_version" in error for error in validate_adapter_pair(
        {"schema_version": 2, "operation_id": "op-1", "authority": "environment", "profile": "staging",
         "credential": {"provider": "aws", "source": "github_oidc"}},
        {},
    ))
    with pytest.raises(ValueError, match="candidate_identity must be an object"):
        DeliveryRequest.from_mapping({
            "operation_id": "op-1", "operation": "validate", "profile": "staging",
            "candidate_identity": None, "requested_at": "2026-09-09T00:00:00Z", "dry_run": True,
        })


def test_artifact_closure_checks_archive_entries_and_candidate_digest(tmp_path: Path):
    archive = tmp_path / "backend.tar"
    with tarfile.open(archive, "w") as tar:
        data = b"runtime"
        info = tarfile.TarInfo("app/main.py")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    digest = "sha256:" + __import__("hashlib").sha256(archive.read_bytes()).hexdigest()
    rc = candidate(component_digest=digest)
    evidence = verify_closure(rc, {"backend": ArtifactSpec("backend", archive, ("app/*.py",))})
    assert evidence["status"] == "PASS"
    assert validate_closure_evidence(evidence) == []
    assert evidence["provenance"]["signature_status"] == "UNSIGNED_OR_UNVERIFIED"


def test_artifact_closure_rejects_missing_runtime_entry(tmp_path: Path):
    archive = tmp_path / "backend.tar"
    with tarfile.open(archive, "w"):
        pass
    digest = "sha256:" + __import__("hashlib").sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ArtifactClosureError, match="required closure entries"):
        verify_closure(candidate(component_digest=digest), {"backend": ArtifactSpec("backend", archive, ("app/*.py",))})


def test_artifact_evidence_rejects_malformed_identity():
    assert "candidate_identity has invalid fields" in validate_closure_evidence({
        "schema_version": 1,
        "status": "PASS",
        "candidate_identity": {
            "release_candidate_id": "rc-hosted",
            "commit_sha": "not-a-commit",
            "artifact_digest": "sha256:" + "a" * 64,
            "profile": "staging",
        },
        "artifacts": {"backend": {}},
        "artifact_digest": "sha256:" + "a" * 64,
        "provenance": {"source": "local", "builder": "test", "signature_status": "UNSIGNED_OR_UNVERIFIED"},
    })


def test_artifact_evidence_binds_identity_digest_and_serialized_artifacts(tmp_path: Path):
    archive = tmp_path / "backend.tar"
    archive.write_bytes(b"runtime")
    digest = "sha256:" + __import__("hashlib").sha256(archive.read_bytes()).hexdigest()
    evidence = verify_closure(candidate(component_digest=digest), {"backend": ArtifactSpec("backend", archive)})

    mismatched_identity = json.loads(json.dumps(evidence))
    mismatched_identity["candidate_identity"]["artifact_digest"] = "sha256:" + "c" * 64
    assert any("candidate_identity.artifact_digest" in error for error in validate_closure_evidence(mismatched_identity))

    mismatched_artifacts = json.loads(json.dumps(evidence))
    mismatched_artifacts["artifacts"]["backend"]["digest"] = "sha256:" + "d" * 64
    assert any("serialized artifact digests" in error for error in validate_closure_evidence(mismatched_artifacts))

    malformed_artifact = json.loads(json.dumps(evidence))
    malformed_artifact["artifacts"]["backend"] = {}
    assert any("artifact backend is missing" in error for error in validate_closure_evidence(malformed_artifact))


def test_profile_operations_require_ttl_and_exact_promotion_identity():
    with pytest.raises(ValueError, match="ttl_hours"):
        request(profile="preview", operation="deploy")
    staging = identity("staging")
    with pytest.raises(ValueError, match="staging_evidence"):
        DeliveryRequest.from_mapping({
            "operation_id": "op-promote", "operation": "promote", "profile": "production-lean",
            "candidate_identity": {**staging, "profile": "production-lean"},
            "requested_at": "2026-09-09T00:00:00Z", "dry_run": True,
        })


def test_dry_run_result_cannot_claim_promotion_and_telemetry_is_registry_shape():
    req = request(profile="production-lean", operation="promote", staging_evidence=identity("production-lean"))
    errors = validate_result(req, {"status": "PROMOTED", "candidate_identity": identity("production-lean")})
    assert "dry-run cannot report a mutating result" in errors
    payload = operation_telemetry(req, {"status": "DRY_RUN"})
    registry = json.loads((ROOT / "config/telemetry_contracts.json").read_text())
    event = next(item for item in registry["events"] if item["id"] == "delivery.operation.completed")
    assert set(payload) <= set(event["fields"])


def test_result_status_and_mutation_are_bound_to_operation():
    validate_request = request(operation="validate", profile="staging", dry_run=False)
    errors = validate_result(
        validate_request,
        {"status": "VALIDATED", "candidate_identity": identity("staging"), "mutation_occurred": True},
    )
    assert "mutation_occurred=false" in " ".join(errors)

    deploy_request = request(operation="deploy", profile="staging", dry_run=False)
    errors = validate_result(
        deploy_request,
        {"status": "SLEPT", "candidate_identity": identity("staging"), "mutation_occurred": True},
    )
    assert any("not valid for deploy" in error for error in errors)

    wake_request = request(operation="wake", profile="staging", dry_run=False)
    errors = validate_result(
        wake_request,
        {"status": "ROLLED_BACK", "candidate_identity": identity("staging"), "mutation_occurred": True},
    )
    assert any("not valid for wake" in error for error in errors)


def test_contract_schemas_validate_sample_request_and_closure(tmp_path: Path):
    request_value = request().as_dict()
    request_schema = json.loads((ROOT / "contracts/delivery/profile-delivery-operation.schema.json").read_text())
    jsonschema.Draft202012Validator(request_schema, resolver=jsonschema.RefResolver.from_schema(request_schema)).validate(request_value)
    archive = tmp_path / "backend.tar"
    archive.write_bytes(b"runtime")
    digest = "sha256:" + __import__("hashlib").sha256(archive.read_bytes()).hexdigest()
    evidence = verify_closure(candidate(component_digest=digest), {"backend": ArtifactSpec("backend", archive)})
    closure_schema = json.loads((ROOT / "contracts/delivery/artifact-closure.schema.json").read_text())
    jsonschema.Draft202012Validator(closure_schema).validate(evidence)
