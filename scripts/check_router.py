#!/usr/bin/env python3
"""Select the minimum meaningful verification set for a change.

Selection is deterministic and read-only.  The router emits the same JSON
locally and in CI; execution is deliberately opt-in via ``--execute``.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.verification_router import (
    LANE_ORDER,
    classify_impact,
    load_router_registry,
    matches as _matches,
)

CONFIG = ROOT / "config" / "verification_router.yaml"


def load_config() -> dict:
    """Return the validated registry in its legacy mapping shape."""
    registry = load_router_registry(CONFIG)
    return {
        "schema_version": registry.schema_version,
        "default_lane": registry.default_lane,
        "lanes": {lane: list(checks) for lane, checks in registry.lanes.items()},
        "checks": {
            check_id: {
                "owner": check.owner,
                "risk": check.risk,
                "command": list(check.command),
                "runtime_budget_seconds": check.runtime_budget_seconds,
            }
            for check_id, check in registry.checks.items()
        },
        "domains": {
            domain_id: {
                "owner": domain.owner,
                "paths": list(domain.paths),
                "checks": list(domain.checks),
                "minimum_lane": domain.minimum_lane,
            }
            for domain_id, domain in registry.domains.items()
        },
        "global_paths": list(registry.global_paths),
    }


def changed_files(base: str | None, explicit: list[str]) -> list[str]:
    if explicit:
        return sorted(set(explicit))
    ref = base or "HEAD"
    proc = subprocess.run(
        ["git", "diff", "--name-only", ref, "--"], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"git diff against {ref} failed")
    return sorted(line for line in proc.stdout.splitlines() if line)


def matches(path: str, pattern: str) -> bool:
    return _matches(path, pattern)


def route(paths: list[str], requested_lane: str | None = None) -> dict:
    cfg = load_router_registry(CONFIG)
    impact = classify_impact(paths, cfg, requested_lane)
    registry = _suite_commands()
    selected = []
    for check_id in impact.selected_checks:
        definition = cfg.checks.get(check_id)
        command = list(definition.command) if definition else registry.get(check_id)
        if not command:
            raise ValueError(f"selected check {check_id!r} has no command definition")
        selected.append({"check_id": check_id, "command": command})
    affected_tests = _affected_tests(impact.changed_files)
    return {
        "schema_version": cfg.schema_version,
        "status": "SELECTED",
        "changed_files": list(impact.changed_files),
        "affected_domains": list(impact.affected_domains),
        "minimum_lane": impact.minimum_lane,
        "selected_lane": impact.selected_lane,
        "followup_required": impact.followup_required,
        "impact": {
            "global_change": impact.global_change,
            "affected_tests": affected_tests,
            "selected_checks": list(impact.selected_checks),
        },
        "checks": selected,
    }


def _affected_tests(changed: tuple[str, ...]) -> list[str]:
    """Expose inventory impact without narrowing the canonical suite command."""
    from scripts.test_inventory import affected, build_inventory, tracked_tests

    config_path = ROOT / "config" / "test_inventory.yaml"
    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    records = build_inventory(config, tracked_tests())
    return sorted(affected(records, list(changed)))


def _suite_commands() -> dict[str, list[str]]:
    sys.path.insert(0, str(ROOT))
    from scripts.lib.test_suites import build_command, load_suites
    return {suite.id: build_command(suite) for suite in load_suites(CONFIG.parent / "test_suites.yaml")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="git revision used for changed-path discovery")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--lane", choices=LANE_ORDER)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = route(changed_files(args.base, args.changed_file), args.lane)
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"schema_version": 1, "status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2
    rendered = json.dumps(result, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.execute:
        for check in result["checks"]:
            command = [sys.executable if part == "python" and i == 0 else part for i, part in enumerate(check["command"])]
            if subprocess.run(command, cwd=ROOT).returncode:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
