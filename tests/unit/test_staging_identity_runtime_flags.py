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


def _terraform_identity_flags(source: str) -> list[str]:
    block = re.search(r"staging_identity_runtime_flags = \[(.*?)\]", source, re.S)
    assert block, "ECS module no longer declares staging_identity_runtime_flags"
    return re.findall(r'"([A-Z0-9_]+)"', block.group(1))


def test_ecs_identity_flags_equal_the_staging_manifest_identity_block():
    assert _terraform_identity_flags(ECS.read_text(encoding="utf-8")) == _manifest_identity_block()


def test_identity_flags_are_default_off_so_the_env_is_load_bearing():
    settings = SETTINGS.read_text(encoding="utf-8")
    for flag in _manifest_identity_block():
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
