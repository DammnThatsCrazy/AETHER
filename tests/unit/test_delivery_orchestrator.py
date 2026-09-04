import argparse
import json
from pathlib import Path

import jsonschema

from scripts import delivery_orchestrator as orchestrator

ROOT = Path(__file__).resolve().parents[2]


def candidate(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "candidate.json"
    value = {"release_candidate_id": "rc-test", "artifact_digest": "sha256:" + "a" * 64}
    value.update(overrides)
    path.write_text(json.dumps(value))
    return path


def staging_args(tmp_path: Path, **overrides):
    values = dict(candidate=candidate(tmp_path), profile="staging", output=tmp_path / "result.json", dry_run=False,
                  preflight_command="", deploy_command="", migration_command="", tenant_activation_command="", journeys_command="")
    values.update(overrides)
    return argparse.Namespace(**values)


def test_staging_dry_run_never_reports_deployed(tmp_path):
    args = staging_args(tmp_path, dry_run=True)
    assert orchestrator.staging(args) == 0
    result = json.loads(args.output.read_text())
    assert result["status"] == "DRY_RUN"
    assert all(check["status"] == "NOT_APPLICABLE" for check in result["checks"])


def test_staging_without_aws_credentials_is_blocked(tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    args = staging_args(tmp_path)
    assert orchestrator.staging(args) == 1
    assert json.loads(args.output.read_text())["status"] == "BLOCKED"


def test_staging_stops_on_missing_command(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "test")
    monkeypatch.setattr(orchestrator, "run", lambda command: ("PASS", "identity") if command.startswith("aws sts") else ("BLOCKED", "required command was not configured"))
    args = staging_args(tmp_path)
    assert orchestrator.staging(args) == 1
    result = json.loads(args.output.read_text())
    assert result["status"] == "BLOCKED"
    assert result["checks"][1]["check_id"] == "preflight"


def test_staging_blocks_incompatible_candidate_profile(tmp_path):
    args = staging_args(tmp_path)
    args.candidate = candidate(tmp_path, deployment_profiles=["production-lean"])
    assert orchestrator.staging(args) == 1
    assert json.loads(args.output.read_text())["checks"][0]["check_id"] == "profile_compatibility"


def test_staging_success_executes_every_ordered_command(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "test")
    observed = []

    def passing(command):
        observed.append(command)
        return "PASS", "passed"

    monkeypatch.setattr(orchestrator, "run", passing)
    args = staging_args(tmp_path, preflight_command="preflight", deploy_command="deploy", migration_command="migrate",
                        tenant_activation_command="activate", journeys_command="journeys")
    assert orchestrator.staging(args) == 0
    result = json.loads(args.output.read_text())
    assert result["status"] == "DEPLOYED"
    assert observed == ["aws sts get-caller-identity --output json", "preflight", "deploy", "migrate", "activate", "journeys"]


def test_migration_requires_database_credentials(tmp_path, monkeypatch):
    metadata = tmp_path / "migration.yaml"
    metadata.write_text("""migration_id: m1
owner: graph
from_version: '1'
to_version: '2'
compatibility: expand_contract
expected_duration_seconds: 60
validation: SELECT 1
repair_strategy: forward_repair
staging_rehearsal_required: true
""")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    args = argparse.Namespace(metadata=metadata, output=tmp_path / "migration.json", command="true", validation_command="true", dry_run=False)
    assert orchestrator.migration(args) == 1
    assert json.loads(args.output.read_text())["status"] == "BLOCKED"


def test_missing_migration_metadata_emits_schema_valid_blocked_evidence(tmp_path):
    metadata = tmp_path / "missing.yaml"
    output = tmp_path / "migration.json"
    args = argparse.Namespace(
        metadata=metadata,
        output=output,
        command="",
        validation_command="",
        dry_run=False,
    )
    assert orchestrator.migration(args) == 1
    result = json.loads(output.read_text())
    schema = json.loads(
        (ROOT / "contracts/delivery/migration-evidence.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(result)
    assert result["status"] == "BLOCKED"
    assert result["migration_id"] is None


def test_registered_unimplemented_journeys_are_blocked(tmp_path):
    args = argparse.Namespace(profile="staging", output=tmp_path / "journeys.json", dry_run=False)
    assert orchestrator.journeys(args) == 1
    result = json.loads(args.output.read_text())
    assert result["status"] == "BLOCKED"
    assert len(result["checks"]) == 5
