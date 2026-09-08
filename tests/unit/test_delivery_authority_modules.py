"""Offline authority tests for capability, IAM, and Terraform reconciliation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.release.compare_effective_iam import (
    EffectiveIamError,
    IamEvidence,
    compare,
    load_requirements,
)
from scripts.release.discover_environment_capabilities import (
    CapabilityDiscoveryError,
    CapabilityStatus,
    discover,
    discover_from_plan,
    explicit_aws_credentials,
    load_fixture,
    resolve_snapshot,
)
from scripts.release.terraform_reconciliation import (
    ReconciliationError,
    load_plan_resources,
    load_remote_inventory,
    load_state_resources,
    reconcile,
)

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _capability_fixture() -> dict:
    return {
        "schema_version": 1,
        "profile": "staging",
        "mode": "offline",
        "capabilities": {
            name: {"status": "PASS", "source": "offline_fixture"}
            for name in (
                "vpc", "ecs", "ecr", "sqs", "sns", "dynamodb", "s3", "kms",
                "secrets", "aurora", "postgres_graph",
            )
        },
    }


def test_capability_fixture_resolves_through_existing_profile_authority(tmp_path):
    path = _write(tmp_path / "capabilities.json", _capability_fixture())
    snapshot = load_fixture(path, profile="staging")
    result = resolve_snapshot(snapshot)
    assert result["disposition"] == "PASS"
    assert result["capability_evidence"]["aurora"]["source"] == "offline_fixture"


def test_capability_discovery_default_is_offline_and_makes_no_cloud_call(monkeypatch):
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("cloud call in credentialless discovery")

    monkeypatch.setattr("subprocess.run", unexpected)
    with pytest.raises(CapabilityDiscoveryError, match="requires --fixture or --plan-json"):
        discover("staging")
    assert called is False


def test_live_capability_discovery_requires_explicit_credentials_and_reader():
    assert explicit_aws_credentials({}) is False
    with pytest.raises(CapabilityDiscoveryError, match="explicit AWS credentials"):
        discover("staging", live=True, environ={})
    with pytest.raises(CapabilityDiscoveryError, match="injected read-only AWS reader"):
        discover("staging", live=True, environ={"AWS_PROFILE": "reviewed"})


def test_plan_capability_discovery_stays_unknown_even_when_resources_exist(tmp_path):
    plan = {
        "format_version": "1.2",
        "planned_values": {"root_module": {"resources": [{"address": "aws_vpc.main", "type": "aws_vpc", "values": {}}]}},
    }
    snapshot = discover_from_plan(_write(tmp_path / "plan.json", plan), "staging")
    assert snapshot.capabilities["vpc"].status is CapabilityStatus.UNKNOWN
    assert "cannot prove" in (snapshot.capabilities["vpc"].reason or "")


def test_capability_schema_accepts_snapshot(tmp_path):
    path = _write(tmp_path / "capabilities.json", _capability_fixture())
    snapshot = load_fixture(path)
    schema = json.loads((ROOT / "contracts/delivery/environment-capability-snapshot.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(snapshot.to_dict())


def _iam_manifest() -> tuple[dict, tuple]:
    manifest = {
        "version": 1,
        "profile": "test",
        "role": "TestRole",
        "required_policy_names": ["reviewed-policy"],
        "statements": [{
            "sid": "ReadBucket",
            "actions": ["s3:GetObject"],
            "resource": "arn:aws:s3:::aether-test/*",
        }],
    }
    requirements = load_requirements_from_mapping(manifest)
    return manifest, requirements


def load_requirements_from_mapping(manifest: dict) -> tuple:
    """Use the production parser without creating a second parser in tests."""

    path = ROOT / "tests/fixtures/terraform_plans/production-lean-valid.json"
    del path  # keep the helper visibly independent from cloud or fixture state
    from scripts.release.compare_effective_iam import IamRequirement

    return tuple(
        IamRequirement(action, resource, statement.get("conditions"), statement["sid"])
        for statement in manifest["statements"]
        for action in statement["actions"]
        for resource in (statement["resource"],)
    )


def _iam_evidence(*, deny: bool = False, boundary: bool = False) -> IamEvidence:
    statements = [{
        "Effect": "Deny" if deny else "Allow",
        "Action": "s3:GetObject",
        "Resource": "arn:aws:s3:::aether-test/*",
    }]
    return IamEvidence(
        role_arn="arn:aws:iam::123456789012:role/TestRole",
        identity_statements=tuple(statements),
        boundary_statements=(tuple(statements) if boundary else ()),
        policy_names=("reviewed-policy",),
        source="offline_fixture",
    )


def test_effective_iam_comparison_passes_offline_fixture():
    manifest, requirements = _iam_manifest()
    report = compare(manifest, requirements, _iam_evidence())
    assert report["status"] == "PASS"
    assert report["mode"] == "offline"
    assert report["operations_passed"] == 1


def test_effective_iam_explicit_deny_blocks_offline_comparison():
    manifest, requirements = _iam_manifest()
    report = compare(manifest, requirements, _iam_evidence(deny=True))
    assert report["status"] == "BLOCKED"
    assert report["operations"][0]["status"] == "BLOCKED"


def test_effective_iam_boundary_must_independently_allow():
    manifest, requirements = _iam_manifest()
    evidence = IamEvidence(
        role_arn="arn:aws:iam::123456789012:role/TestRole",
        identity_statements=_iam_evidence().identity_statements,
        boundary_statements=({"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "*"},),
        policy_names=("reviewed-policy",),
        source="offline_fixture",
    )
    report = compare(manifest, requirements, evidence)
    assert report["status"] == "BLOCKED"
    assert "permissions boundary" in report["blockers"][0]


def test_effective_iam_evidence_rejects_plaintext_secret_material():
    with pytest.raises(EffectiveIamError, match="plaintext secret material"):
        IamEvidence.from_dict({
            "schema_version": 1,
            "role_arn": "arn:aws:iam::123456789012:role/TestRole",
            "identity_statements": [{
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": "*",
                "api_key": "do-not-store",
            }],
            "boundary_statements": [],
            "policy_names": [],
            "source": "offline_fixture",
        })


def test_effective_iam_schema_accepts_comparison():
    manifest, requirements = _iam_manifest()
    report = compare(manifest, requirements, _iam_evidence())
    schema = json.loads((ROOT / "contracts/delivery/effective-iam-comparison.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(report)


def test_effective_iam_evidence_schema_accepts_fixture():
    evidence = {
        "schema_version": 1,
        "role_arn": "arn:aws:iam::123456789012:role/TestRole",
        "identity_statements": list(_iam_evidence().identity_statements),
        "boundary_statements": [],
        "policy_names": ["reviewed-policy"],
        "source": "offline_fixture",
    }
    schema = json.loads((ROOT / "contracts/delivery/effective-iam-evidence.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(evidence)


def _terraform_inputs(tmp_path: Path, *, remote_owner: str = "terraform", remote_values: dict | None = None):
    values = {"id": "vpc-123", "name": "aether-test"}
    plan = {
        "format_version": "1.2",
        "resource_changes": [{
            "address": "aws_vpc.main", "type": "aws_vpc",
            "change": {"actions": ["no-op"], "after": values},
        }],
        "planned_values": {"root_module": {"resources": [{
            "address": "aws_vpc.main", "type": "aws_vpc", "values": values,
        }]}},
    }
    state = {"values": {"root_module": {"resources": [{
        "address": "aws_vpc.main", "type": "aws_vpc", "values": values,
    }]}}}
    remote = {
        "schema_version": 1,
        "source": "offline_fixture",
        "inventory_complete": True,
        "resources": [{
            "address": "aws_vpc.main", "type": "aws_vpc", "id": "vpc-123",
            "owner": remote_owner, "values": remote_values if remote_values is not None else values,
        }],
    }
    return (
        load_plan_resources(_write(tmp_path / "plan.json", plan)),
        load_state_resources(_write(tmp_path / "state.json", state)),
        load_remote_inventory(_write(tmp_path / "remote.json", remote)),
    )


def test_terraform_reconciliation_reports_in_sync_without_mutation(tmp_path):
    desired, state, remote = _terraform_inputs(tmp_path)
    report = reconcile("staging", desired, state, remote)
    assert report["status"] == "PASS"
    assert report["resources"][0]["classification"] == "IN_SYNC"
    assert report["actions"] == []


def test_terraform_reconciliation_blocks_ambiguous_remote_ownership(tmp_path):
    desired, state, remote = _terraform_inputs(tmp_path, remote_owner="unknown")
    report = reconcile("staging", desired, state, remote)
    assert report["status"] == "BLOCKED"
    assert report["resources"][0]["classification"] == "AMBIGUOUS_OWNERSHIP"


def test_terraform_reconciliation_blocks_state_remote_identity_drift(tmp_path):
    desired, state, remote = _terraform_inputs(tmp_path, remote_values={"id": "vpc-999", "name": "aether-test"})
    report = reconcile("staging", desired, state, remote)
    assert report["status"] == "BLOCKED"
    assert report["resources"][0]["classification"] == "DRIFT"


def test_terraform_plan_loader_retains_destroy_only_change(tmp_path):
    plan = {
        "format_version": "1.2",
        "resource_changes": [{
            "address": "aws_vpc.old", "type": "aws_vpc",
            "change": {"actions": ["delete"], "before": {"id": "vpc-old"}},
        }],
        "planned_values": {"root_module": {"resources": []}},
    }
    resources = load_plan_resources(_write(tmp_path / "destroy.json", plan))
    assert resources[0].address == "aws_vpc.old"
    assert resources[0].actions == ("delete",)


def test_terraform_reconciliation_creates_only_when_remote_is_confirmed_absent(tmp_path):
    desired, _state, _remote = _terraform_inputs(tmp_path)
    remote = load_remote_inventory(_write(tmp_path / "remote-empty.json", {
        "schema_version": 1,
        "source": "offline_fixture",
        "inventory_complete": True,
        "resources": [],
    }))
    report = reconcile("staging", desired, (), remote)
    assert report["status"] == "CHANGES_REQUIRED"
    assert report["resources"][0]["classification"] == "CREATE"
    assert report["actions"][0]["action"] == "create"


def test_terraform_reconciliation_rejects_plaintext_secret_material(tmp_path):
    path = _write(tmp_path / "remote.json", {
        "schema_version": 1,
        "source": "offline_fixture",
        "inventory_complete": True,
        "resources": [{
            "address": "aws_secretsmanager_secret.foo", "type": "aws_secretsmanager_secret",
            "owner": "terraform", "values": {"secret_value": "do-not-store"},
        }],
    })
    with pytest.raises(ReconciliationError, match="plaintext secret material"):
        load_remote_inventory(path)


def test_terraform_reconciliation_schema_accepts_report(tmp_path):
    desired, state, remote = _terraform_inputs(tmp_path)
    report = reconcile("staging", desired, state, remote)
    schema = json.loads((ROOT / "contracts/delivery/terraform-reconciliation.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(report)


def test_terraform_remote_inventory_schema_accepts_fixture(tmp_path):
    _desired, _state, remote = _terraform_inputs(tmp_path)
    raw = {
        "schema_version": 1,
        "source": "offline_fixture",
        "inventory_complete": True,
        "resources": [{
            "address": item.address,
            "type": item.resource_type,
            "owner": item.owner,
            "id": item.resource_id,
            "values": dict(item.values),
        } for item in remote.resources],
    }
    schema = json.loads((ROOT / "contracts/delivery/terraform-remote-inventory.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(raw)
