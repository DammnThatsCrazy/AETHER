"""Staging tasks must carry the identity runtime flags the staging manifest turns on.

config/release/feature_flags/staging.yaml declares the Identity Continuity runtime
"staging ON for proof", but those flags default off in settings.py and nothing
passed them to the ECS task. Staging therefore ran with identity resolution
disabled (rehearsal run 43365158651). The ECS module now sets them on staging
tasks only; this test keeps that list equal to the manifest's identity block.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ECS = ROOT / "infra/aws/terraform/modules/ecs/main.tf"
STAGING_FLAGS = ROOT / "config/release/feature_flags/staging.yaml"
SETTINGS = ROOT / "services/api/config/settings.py"


def _manifest_identity_block() -> list[str]:
    lines = STAGING_FLAGS.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if "Identity Continuity runtime" in line)
    flags = []
    for line in lines[start + 1:]:
        match = re.fullmatch(r"\s+- ([A-Z0-9_]+)", line)
        if not match:
            break
        flags.append(match.group(1))
    assert flags, "staging manifest identity block is empty"
    return flags


def _manifest_task_environment() -> list[str]:
    flags = yaml.safe_load(STAGING_FLAGS.read_text(encoding="utf-8"))["runtime"]["flags"]
    return list(flags["task_environment"])


def test_task_environment_is_the_manifest_identity_block():
    assert _manifest_task_environment() == _manifest_identity_block()


def test_ecs_reads_the_task_environment_from_the_manifest():
    # The ECS module derives the flags from the manifest instead of keeping a
    # copy, so adding a flag to task_environment switches it on in staging.
    source = ECS.read_text(encoding="utf-8")
    assert re.search(
        r'staging_identity_runtime_flags = yamldecode\(\s*file\("\$\{path\.module\}/\.\./\.\./\.\./\.\./\.\./'
        r'config/release/feature_flags/staging\.yaml"\)\s*\)\.runtime\.flags\.task_environment',
        source,
    )
    resolved = (ECS.parent / "../../../../../config/release/feature_flags/staging.yaml").resolve()
    assert resolved == STAGING_FLAGS.resolve()
    assert '"IDENTITY_RESOLUTION_ENABLED"' not in source  # no hand-kept copy


def test_identity_flags_are_default_off_so_the_env_is_load_bearing():
    settings = SETTINGS.read_text(encoding="utf-8")
    for flag in _manifest_task_environment():
        assert re.search(rf'_env_bool\(\s*"{flag}",\s*False\s*\)', settings), (
            f"{flag} is not a default-off setting; the staging env would not change it"
        )


def test_identity_flags_reach_every_staging_task_and_only_staging():
    source = ECS.read_text(encoding="utf-8")
    assert re.search(
        r'identity_runtime_environment = var\.deployment_profile == "staging" \? \[.*?\] : \[\]',
        source, re.S,
    )
    # Backend and worker container definitions both merge the lane locals.
    assert source.count("local.identity_runtime_environment,") == 2
    assert source.count("local.kyber_runtime_environment,") == 2


def test_terraform_revisions_carry_the_deployment_identity():
    # Delivery sets AETHER_DEPLOYMENT_ID on the revisions it registers; a
    # Terraform-registered revision rolled out without delivery used to lack
    # it, and the staging proof capture then answered 503.
    source = ECS.read_text(encoding="utf-8")
    assert re.search(
        r'deployment_identity_environment = \[\s*\{ name = "AETHER_DEPLOYMENT_ID", value = var\.backend_image_digest \},\s*\]',
        source,
    )
    assert source.count("local.deployment_identity_environment,") == 2


def _validate_staging_manifest_with(tmp_path, mutate) -> list[str]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_resolved_feature_flags", ROOT / "scripts/release/check_resolved_feature_flags.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # validate() only uses ROOT to label the manifest; settings and pyproject
    # paths were already resolved against the real repository at import.
    module.ROOT = tmp_path
    data = yaml.safe_load(STAGING_FLAGS.read_text(encoding="utf-8"))
    mutate(data["runtime"]["flags"])
    path = tmp_path / "staging.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return module.validate(path)


def test_validator_rejects_task_environment_flags_that_are_not_on(tmp_path):
    def drop_from_on(flags):
        flags["on"].remove("IDENTITY_RESOLUTION_ENABLED")
    errors = _validate_staging_manifest_with(tmp_path, drop_from_on)
    assert any("task_environment flags must also be ON" in e for e in errors), errors


def test_validator_rejects_default_on_flags_in_task_environment(tmp_path):
    def add_default_on(flags):
        flags["task_environment"].append("TRUST_PLANE_ENABLED")
    errors = _validate_staging_manifest_with(tmp_path, add_default_on)
    assert any("only default-off flags" in e for e in errors), errors


def test_validator_accepts_the_checked_in_manifest(tmp_path):
    assert _validate_staging_manifest_with(tmp_path, lambda flags: None) == []
