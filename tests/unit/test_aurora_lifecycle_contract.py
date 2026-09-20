"""Contract checks for the stateful Aurora deletion backstops."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "deploy/aws/terraform"


def _resource_block(source: str, resource_type: str, name: str) -> str:
    match = re.search(
        rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(name)}"\s*\{{',
        source,
    )
    assert match, f"missing {resource_type}.{name} resource"
    depth = 0
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"unterminated {resource_type}.{name} resource")


def test_aurora_stateful_resources_have_destroy_backstops() -> None:
    source = (TF / "modules/aurora/main.tf").read_text(encoding="utf-8")
    for resource_type, name in (
        ("aws_kms_key", "aurora"),
        ("aws_rds_cluster", "this"),
        ("aws_rds_cluster_instance", "writer"),
    ):
        block = _resource_block(source, resource_type, name)
        assert re.search(
            r"lifecycle\s*\{\s*prevent_destroy\s*=\s*true\s*\}",
            block,
            re.DOTALL,
        ), f"{resource_type}.{name} can be destroyed by a profile toggle"


def test_staging_aurora_has_the_aws_deletion_guard() -> None:
    source = (TF / "main.tf").read_text(encoding="utf-8")
    assert 'deletion_protection = var.environment == "production" || var.environment == "staging"' in source


def test_decommission_runbook_names_aurora_protection() -> None:
    source = (TF / "DECOMMISSION.md").read_text(encoding="utf-8")
    assert "`modules/aurora`" in source
    assert "aws_rds_cluster.this" in source
    assert "skip_aurora" in source
