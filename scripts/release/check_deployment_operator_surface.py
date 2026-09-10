#!/usr/bin/env python3
"""Validate the GitHub-only deployment operator boundary.

The deployment operator is deliberately separate from Kyber. GitHub Actions
owns application delivery and Terraform promotion; Kyber may only display
readiness evidence. This check keeps that decision executable and reviewable
instead of relying on a UI convention or documentation claim.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config/deployment_operator_surface.yaml"
WORKFLOW_DIR = ROOT / ".github/workflows"
KYBER_SOURCE = ROOT / "frontend/kyber/src"

EXPECTED_EXECUTION_PATHS = {
    ".github/workflows/deploy.yml": {"push", "workflow_dispatch"},
    ".github/workflows/terraform-promote.yml": {"workflow_dispatch"},
}
MUTATION_ENDPOINT = re.compile(
    r"\b(?:post|put|patch|delete)\s*\([^\n)]*['\"][^'\"]*deployment",
    re.IGNORECASE,
)


def _triggers(document: dict[str, Any]) -> set[str]:
    # YAML 1.1 treats the bare ``on`` key as boolean True.
    value = document.get("on", document.get(True))
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, dict):
        return {str(item) for item in value}
    return set()


def _workflow_runs(document: dict[str, Any]):
    for job_name, job in (document.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            run = step.get("run")
            if run:
                yield str(job_name), str(step.get("name", "<unnamed>")), str(run)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return value


def validate(
    *,
    config_path: Path = DEFAULT_CONFIG,
    root: Path = ROOT,
) -> list[str]:
    """Return policy violations; an empty list means the boundary holds."""

    errors: list[str] = []
    try:
        config = _load_yaml(config_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"cannot load deployment operator policy: {exc}"]

    if config.get("schema_version") != 1:
        errors.append("policy schema_version must be 1")
    surface = config.get("operator_surface")
    if not isinstance(surface, dict):
        errors.append("operator_surface must be a mapping")
        surface = {}
    if surface.get("system") != "github_actions":
        errors.append("operator_surface.system must be github_actions")

    configured_paths = surface.get("execution_paths")
    if not isinstance(configured_paths, list):
        errors.append("operator_surface.execution_paths must be a list")
        configured_paths = []
    configured: dict[str, dict[str, Any]] = {}
    for entry in configured_paths:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("each execution path must declare a string path")
            continue
        path = entry["path"]
        if path in configured:
            errors.append(f"duplicate execution path: {path}")
        configured[path] = entry
        expected_triggers = EXPECTED_EXECUTION_PATHS.get(path)
        if expected_triggers is None:
            errors.append(f"unreviewed deployment execution path: {path}")
        elif set(entry.get("trigger_policy") or []) != expected_triggers:
            errors.append(
                f"{path}: trigger_policy must be {sorted(expected_triggers)}"
            )

        workflow_path = root / path
        if not workflow_path.is_file():
            errors.append(f"deployment execution workflow is missing: {path}")
            continue
        try:
            workflow = _load_yaml(workflow_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{path}: cannot parse workflow: {exc}")
            continue
        actual_triggers = _triggers(workflow)
        if expected_triggers is not None and actual_triggers != expected_triggers:
            errors.append(
                f"{path}: workflow triggers are {sorted(actual_triggers)}, "
                f"expected {sorted(expected_triggers)}"
            )

    if set(configured) != set(EXPECTED_EXECUTION_PATHS):
        errors.append(
            "execution_paths must name exactly the reviewed GitHub workflows: "
            + ", ".join(sorted(EXPECTED_EXECUTION_PATHS))
        )

    apply_path = surface.get("terraform_apply_path")
    if apply_path != ".github/workflows/terraform-promote.yml":
        errors.append("terraform_apply_path must be the reviewed promotion workflow")

    kyber = config.get("kyber")
    if not isinstance(kyber, dict):
        errors.append("kyber must be a mapping")
        kyber = {}
    if kyber.get("enabled") is not False:
        errors.append("kyber deployment controls must be disabled")
    if kyber.get("posture") != "read_only":
        errors.append("kyber deployment posture must be read_only")
    if kyber.get("mutation_controls") != []:
        errors.append("kyber mutation_controls must be an empty list")

    # Scan every live workflow run block, not comments or inactive nested text.
    # This complements the policy's exact path list and prevents a new live
    # workflow from acquiring a second Terraform apply site.
    live_apply_sites: list[str] = []
    workflow_dir = root / ".github/workflows"
    for workflow_path in sorted(workflow_dir.glob("*.y*ml")):
        try:
            workflow = _load_yaml(workflow_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{workflow_path.relative_to(root)}: cannot parse workflow: {exc}")
            continue
        for job_name, step_name, run in _workflow_runs(workflow):
            if "terraform apply" in run:
                live_apply_sites.append(
                    f"{workflow_path.relative_to(root)}:{job_name}:{step_name}"
                )
    expected_apply_prefix = ".github/workflows/terraform-promote.yml:"
    unexpected_apply_sites = [
        site for site in live_apply_sites if not site.startswith(expected_apply_prefix)
    ]
    if unexpected_apply_sites:
        errors.append(
            "Terraform apply escaped the reviewed GitHub workflow: "
            + ", ".join(unexpected_apply_sites)
        )

    page = root / "frontend/kyber/src/pages/deployment-readiness/deployment-readiness-page.tsx"
    try:
        page_text = page.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read Kyber deployment readiness page: {exc}")
        page_text = ""
    for required_text in (
        "Deployment execution is disabled in Kyber",
        "GitHub Actions",
        "read-only readiness",
    ):
        if required_text not in page_text:
            errors.append(f"Kyber readiness page is missing boundary copy: {required_text}")

    for source_path in sorted(KYBER_SOURCE.rglob("*.ts*")):
        text = source_path.read_text(encoding="utf-8")
        if MUTATION_ENDPOINT.search(text):
            errors.append(
                "Kyber contains a deployment mutation endpoint: "
                + str(source_path.relative_to(root))
            )
        if "gh workflow run" in text:
            errors.append(
                "Kyber must not dispatch GitHub workflows: "
                + str(source_path.relative_to(root))
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    errors = validate(config_path=args.config, root=ROOT)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Deployment operator surface: GitHub Actions only; Kyber controls disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
