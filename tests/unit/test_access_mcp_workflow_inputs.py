from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import validate_access_mcp_inputs as validator  # noqa: E402


def _validate(**overrides: object) -> None:
    values: dict[str, object] = {
        "profile": "production",
        "enable_repository": "true",
        "enable_service": "true",
        "image_digest": "sha256:" + "a" * 64,
        "desired_count": "2",
        "allowed_origins_json": '["https://console.example.test"]',
        "access_mcp_path": "/v1/access/mcp",
    }
    values.update(overrides)
    validator.validate_inputs(**values)  # type: ignore[arg-type]


def _workflow(name: str) -> dict[str, object]:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def test_hosted_access_kit_workflow_checks_container_and_npm_artifacts() -> None:
    workflow = _workflow("access-kit-container.yml")
    assert workflow["jobs"]["build-and-smoke"]["runs-on"] == "ubuntu-latest"
    steps = workflow["jobs"]["build-and-smoke"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "npm pack ./packages/access-kit --dry-run" in commands
    assert "--platform linux/amd64" in commands
    assert "/readyz" in commands


def test_image_publication_fails_closed_without_production_reviewers() -> None:
    workflow = _workflow("publish-access-mcp-image.yml")
    jobs = workflow["jobs"]
    reviewer_gate = jobs["require-production-reviewers"]
    gate_script = "\n".join(step.get("run", "") for step in reviewer_gate["steps"])
    assert reviewer_gate.get("environment") is None
    assert reviewer_gate["permissions"] == {"actions": "read", "contents": "read"}
    assert "environments/production" in gate_script
    assert '"required_reviewers"' in gate_script
    assert jobs["publish"]["needs"] == "require-production-reviewers"
    assert jobs["publish"]["environment"] == "production"
    assert workflow["permissions"]["id-token"] == "write"


def test_npm_release_publishes_the_reviewed_tarball_only_after_review_gate() -> None:
    workflow = _workflow("publish-access-kit.yml")
    dispatch = workflow.get("on", workflow.get(True))
    inputs = dispatch["workflow_dispatch"]["inputs"]
    assert inputs["dry_run"]["default"] is True

    jobs = workflow["jobs"]
    validation = jobs["validate-package"]
    validation_script = "\n".join(step.get("run", "") for step in validation["steps"])
    assert validation.get("environment") is None
    assert "pnpm --filter @aether/access-kit test" in validation_script
    assert "npm pack ./packages/access-kit --pack-destination" in validation_script

    reviewer_gate = jobs["require-npm-release-reviewers"]
    gate_script = "\n".join(step.get("run", "") for step in reviewer_gate["steps"])
    assert reviewer_gate.get("environment") is None
    assert "environments/npm-production" in gate_script
    assert '"required_reviewers"' in gate_script
    assert "&& !inputs.dry_run" in reviewer_gate["if"]

    publish = jobs["publish-package"]
    assert publish["needs"] == ["validate-package", "require-npm-release-reviewers"]
    assert publish["environment"] == "npm-production"
    publish_script = "\n".join(step.get("run", "") for step in publish["steps"])
    assert 'npm publish "$RUNNER_TEMP/access-kit-package/$TARBALL"' in publish_script
    assert "secrets.NPM_TOKEN" in str(publish)


def test_accepts_canonical_production_scale_deployment() -> None:
    _validate(
        allowed_origins_json=(
            '["https://console.example.test",'
            '"https://console.example.test:65535",'
            '"https://192.0.2.10:1"]'
        )
    )


@pytest.mark.parametrize("profile", ["staging", "production-scale", "preview"])
def test_rejects_noncanonical_repository_owner(profile: str) -> None:
    with pytest.raises(ValueError, match="production state owner"):
        _validate(profile=profile, enable_service="false", image_digest="")


def test_service_requires_repository_and_digest() -> None:
    with pytest.raises(ValueError, match="enable_access_mcp_repository"):
        _validate(enable_repository="false")
    with pytest.raises(ValueError, match="immutable access_mcp_image_digest"):
        _validate(image_digest="")


@pytest.mark.parametrize(
    "origin",
    [
        "https://bad..example.test",
        "https://-bad.example.test",
        "https://bad-.example.test",
        "https://bad_host.example.test",
        "https://256.1.2.3",
        "https://console.example.test:0",
        "https://console.example.test:65536",
        "https://console.example.test:99999",
        "https://console.example.test:000001",
        "https://console.example.test:abc",
        "https://console.example.test:",
        "https://user@console.example.test",
        "https://console.example.test/path",
        "https://[2001:db8::1]",
    ],
)
def test_rejects_invalid_host_or_port(origin: str) -> None:
    with pytest.raises(ValueError, match="allowed_origins"):
        _validate(allowed_origins_json=json.dumps([origin]))


@pytest.mark.parametrize("path", ["/mcp", "/mcp/foo", "/McpOperator"])
def test_rejects_path_overlapping_reserved_tfmcp_route(path: str) -> None:
    with pytest.raises(ValueError, match="reserved /mcp\*"):
        _validate(access_mcp_path=path)


@pytest.mark.parametrize("count", ["0", "5", "2.0", "", "01"])
def test_rejects_unbounded_or_noninteger_task_count(count: str) -> None:
    with pytest.raises(ValueError, match="desired_count"):
        _validate(desired_count=count)


def test_workflow_invokes_validator_and_passes_same_path_to_terraform() -> None:
    workflow = (ROOT / ".github" / "workflows" / "terraform-promote.yml").read_text()
    assert "python scripts/release/validate_access_mcp_inputs.py" in workflow
    assert "TF_VAR_access_mcp_path: ${{ inputs.access_mcp_path || '/v1/access/mcp' }}" in workflow
    assert "ACCESS_MCP_PATH: ${{ inputs.access_mcp_path || '/v1/access/mcp' }}" in workflow


def test_task_definition_pins_access_mcp_image_by_digest() -> None:
    module = (ROOT / "infra" / "aws" / "terraform" / "modules" / "access_mcp" / "main.tf").read_text()
    assert 'image     = "${var.ecr_repository_url}@${var.image_digest}"' in module
