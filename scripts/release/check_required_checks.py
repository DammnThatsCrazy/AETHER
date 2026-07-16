#!/usr/bin/env python3
"""Validate the canonical release-check catalog against hosted workflows.

The catalog is the authority consumed by release evidence.  This validator
prevents a required SDK job from disappearing, becoming non-PR-triggered, or
losing the shared-contract trigger that makes cross-platform validation
authoritative before merge.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config/required_release_checks.yaml"
SHARED_TRIGGER = "packages/shared/**"
ALLOWED_RUNNERS = {"ubuntu", "macos", "windows"}


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    catalog_path = root / "config/required_release_checks.yaml"
    try:
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot load required-check catalog: {exc}"]
    checks = catalog.get("checks") or []
    if not checks:
        return ["required-check catalog declares no checks"]
    branch = catalog.get("branch_protection") or {}
    if branch.get("branch") != "main" or branch.get("verification_required_for_release") is not True:
        errors.append("branch protection must require external verification for main")
    if not branch.get("unavailable_action"):
        errors.append("branch protection must declare the action when GitHub evidence is unavailable")
    ids: set[str] = set()
    workflows: dict[str, tuple[dict, str]] = {}
    for check in checks:
        check_id = str(check.get("id", ""))
        if not check_id or check_id in ids:
            errors.append(f"missing or duplicate check id: {check_id!r}")
        ids.add(check_id)
        for field in ("workflow", "job", "applicability", "runner_class", "evidence_artifact"):
            if not check.get(field):
                errors.append(f"{check_id or '?'}: missing {field}")
        if check.get("runner_class") not in ALLOWED_RUNNERS:
            errors.append(f"{check_id}: unknown runner_class {check.get('runner_class')!r}")
        if not any(check.get(flag) is True for flag in (
            "blocks_pr_merge", "blocks_sdk_release", "blocks_founding_tenant_release"
        )):
            errors.append(f"{check_id}: check does not block any release surface")
        rel = str(check.get("workflow", ""))
        if rel not in workflows:
            path = root / rel
            try:
                text = path.read_text(encoding="utf-8")
                doc = yaml.safe_load(text) or {}
                workflows[rel] = (doc, text)
            except (OSError, yaml.YAMLError) as exc:
                errors.append(f"{check_id}: cannot load workflow {rel}: {exc}")
                continue
        doc, text = workflows[rel]
        if check.get("job") not in (doc.get("jobs") or {}):
            errors.append(f"{check_id}: workflow has no job {check.get('job')!r}")
        # PyYAML treats the YAML 1.1 word `on` as a boolean, so use source text
        # for trigger checks rather than accepting an ambiguous parsed key.
        if "pull_request:" not in text:
            errors.append(f"{check_id}: workflow is not triggered for pull requests")
        if "shared_contracts" in (check.get("applicability") or []) and SHARED_TRIGGER not in text:
            errors.append(f"{check_id}: workflow does not trigger on {SHARED_TRIGGER}")
        artifact = str(check.get("evidence_artifact", ""))
        if artifact and f"name: {artifact}" not in text:
            errors.append(f"{check_id}: workflow does not upload evidence artifact {artifact!r}")
    conclusions = catalog.get("allowed_terminal_conclusions")
    if conclusions != ["success"]:
        errors.append("allowed_terminal_conclusions must be exactly [success]")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Required release-check validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Required release-check validation passed: catalog and hosted SDK jobs agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
