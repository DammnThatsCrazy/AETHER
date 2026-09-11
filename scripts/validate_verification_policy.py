#!/usr/bin/env python3
"""Validate the single verification-authority policy registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/verification_policy.yaml"
LANES = {"fast", "pr", "integration", "regression", "release"}
RISKS = {f"R{i}" for i in range(6)}


def _mapping(value: Any, where: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{where} must be a mapping")
        return {}
    return value


def validate(path: Path = POLICY) -> list[str]:
    errors: list[str] = []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot load verification policy: {exc}"]
    top = _mapping(raw, "verification policy", errors)
    if top.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if top.get("authority") != "verification":
        errors.append("authority must be verification")
    if top.get("status_check") != "verification / disposition":
        errors.append("status_check must be the stable 'verification / disposition' check")

    normal = _mapping(top.get("normal_pr"), "normal_pr", errors)
    if normal.get("blocking") is not True:
        errors.append("normal_pr.blocking must be true")
    for key in ("universal_fast_lane", "affected_lane"):
        if normal.get(key) not in LANES:
            errors.append(f"normal_pr.{key} must name a known lane")
    escalations = normal.get("allowed_escalations")
    if not isinstance(escalations, list) or not set(escalations) <= LANES:
        errors.append("normal_pr.allowed_escalations must contain only known lanes")

    shadow = _mapping(top.get("shadow"), "shadow", errors)
    if shadow.get("enabled") is not True:
        errors.append("shadow.enabled must be true during the observation period")
    if shadow.get("command") != "make ci-check":
        errors.append("shadow.command must remain make ci-check")
    if shadow.get("blocking") is not False:
        errors.append("shadow.blocking must be false")
    exit_condition = _mapping(shadow.get("exit_condition"), "shadow.exit_condition", errors)
    for key in ("representative_pr_window", "zero_unexplained_selection_misses", "ordinary_pr_p95_within_budget"):
        if exit_condition.get(key) is not True:
            errors.append(f"shadow.exit_condition.{key} must be true")

    release = _mapping(top.get("release"), "release", errors)
    if release.get("blocking_on_pr") is not False:
        errors.append("release.blocking_on_pr must be false")
    if release.get("command") != "make release-gate":
        errors.append("release.command must remain make release-gate")

    risk_lanes = _mapping(top.get("risk_lanes"), "risk_lanes", errors)
    if set(risk_lanes) != RISKS:
        errors.append("risk_lanes must define exactly R0 through R5")
    for risk, lane in risk_lanes.items():
        if risk in RISKS and lane not in LANES:
            errors.append(f"risk_lanes.{risk} must name a known lane")
    return errors


def main() -> int:
    errors = validate()
    print(json.dumps({"schema_version": 1, "status": "FAILED" if errors else "PASS", "errors": errors}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
