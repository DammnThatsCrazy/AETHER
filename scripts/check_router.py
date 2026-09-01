#!/usr/bin/env python3
"""Select the minimum meaningful verification set for a change.

Selection is deterministic and read-only.  The router emits the same JSON
locally and in CI; execution is deliberately opt-in via ``--execute``.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "verification_router.yaml"
LANE_ORDER = ("fast", "pr", "integration", "regression", "release")


def load_config() -> dict:
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("verification router schema_version must be 1")
    return data


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
    # fnmatch's ** behavior is sufficient for repository-relative paths, but
    # also treat a trailing /** as matching the directory itself.
    return fnmatch.fnmatchcase(path, pattern) or (
        pattern.endswith("/**") and (path == pattern[:-3] or path.startswith(pattern[:-2]))
    )


def route(paths: list[str], requested_lane: str | None = None) -> dict:
    cfg = load_config()
    domains: set[str] = set()
    checks: set[str] = set(cfg["lanes"]["fast"][:2])
    minimum = "fast"
    global_change = any(any(matches(path, pat) for pat in cfg["global_paths"]) for path in paths)
    matched_definitions = []
    for name, definition in cfg["domains"].items():
        if global_change or any(matches(path, pat) for path in paths for pat in definition["paths"]):
            domains.add(name)
            matched_definitions.append(definition)
            if LANE_ORDER.index(definition["minimum_lane"]) > LANE_ORDER.index(minimum):
                minimum = definition["minimum_lane"]
    lane = requested_lane or minimum
    # Fast is deliberately available as bounded local evidence even when the
    # change requires a stronger merge lane. Other explicit downgrades are an
    # unsafe attempt to substitute a weaker gate and remain blocked.
    if lane != "fast" and LANE_ORDER.index(lane) < LANE_ORDER.index(minimum):
        raise ValueError(f"requested lane {lane!r} is below required minimum {minimum!r}")
    if LANE_ORDER.index(lane) >= LANE_ORDER.index(minimum):
        for definition in matched_definitions:
            checks.update(definition["checks"])
    checks.update(cfg["lanes"][lane])
    registry = _suite_commands()
    definitions = cfg["checks"]
    selected = []
    for check_id in sorted(checks):
        definition = definitions.get(check_id)
        command = definition["command"] if definition else registry.get(check_id)
        if not command:
            raise ValueError(f"selected check {check_id!r} has no command definition")
        selected.append({"check_id": check_id, "command": command})
    return {
        "schema_version": 1,
        "status": "SELECTED",
        "changed_files": paths,
        "affected_domains": sorted(domains),
        "minimum_lane": minimum,
        "selected_lane": lane,
        "followup_required": LANE_ORDER.index(lane) < LANE_ORDER.index(minimum),
        "checks": selected,
    }


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
