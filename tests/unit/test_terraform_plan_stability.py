"""Guard Terraform identity and apply semantics against recurring plan noise."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_secret_rotation_schedule_uses_stable_secret_arn_identity():
    rotation = (
        ROOT / "deploy/aws/terraform/modules/secrets/rotation.tf"
    ).read_text(encoding="utf-8")

    schedule = re.search(
        r'resource\s+"aws_secretsmanager_secret_rotation"\s+"this"\s*'
        r"\{(?:(?!\n\}).)*",
        rotation,
        flags=re.DOTALL,
    )

    assert schedule is not None, "the managed secret-rotation schedule is missing"
    assert re.search(
        r"secret_id\s*=\s*aws_secretsmanager_secret\.this\[each\.key\]\.arn\b",
        schedule.group(),
    ), "rotation schedules must use the ARN to avoid name/ARN identity replacement"


def test_shared_preload_libraries_requires_reboot_explicitly():
    aurora = (
        ROOT / "deploy/aws/terraform/modules/aurora/main.tf"
    ).read_text(encoding="utf-8")

    parameter = re.search(
        r"parameter\s*\{\s*"
        r'name\s*=\s*"shared_preload_libraries"\s*'
        r'value\s*=\s*"pg_stat_statements"\s*'
        r'apply_method\s*=\s*"pending-reboot"\s*'
        r"\}",
        aurora,
    )

    assert parameter is not None, (
        "shared_preload_libraries must explicitly use pending-reboot"
    )
