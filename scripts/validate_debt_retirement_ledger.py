#!/usr/bin/env python3
"""Validate the technical-debt retirement ledger and report repository size.

The ledger (``config/debt_retirement_ledger.yaml``) is the enforceable cutover
registry for the architecture reset: one row per duplicated authority, with the
consumers that keep it alive, the evidence required before it may be deleted,
and a deadline so a compatibility layer cannot become permanent.

``--report`` prints the current repository-size measurements next to the
recorded baseline so a cutover PR can show that it removed more than it added.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "config/debt_retirement_ledger.yaml"

STATES = {"retain", "converge", "deprecated", "deletion-ready", "removed"}
CLASSIFICATIONS = {
    "core", "beta", "experimental", "internal", "deprecated", "archived", "removed",
}
DOMAINS = {
    "intake", "evidence", "normalization", "identity", "graph", "intelligence",
    "action", "product", "delivery", "verification", "repository",
}
MECHANISMS = {
    "adapter", "dual-write", "dual-read", "alias", "migration", "delete", "none",
}
REQUIRED = (
    "id", "domain", "classification", "state", "authority", "current", "duplicates",
    "consumers", "compatibility", "mechanism", "rollback", "deadline", "retire",
)
# Policy-bearing fields: a row with a null or blank value has no owner, no
# compatibility promise or no way back, which is what the ledger exists to force.
TEXT_FIELDS = ("authority", "compatibility", "rollback", "retire")
# A row may only be deleted once it can show both of these.
DELETION_EVIDENCE = ("parity_evidence", "usage_evidence")
# Every metric ``measure()`` reports needs a baseline value, so ``--report`` can
# always show a delta. ``test_measure_reports_exactly_the_baseline_metrics``
# keeps this tuple and ``measure()`` in step.
METRIC_KEYS = (
    "tracked_files", "files_services", "files_frontend", "files_tests", "files_docs",
    "files_docs_archive", "files_packages", "files_scripts", "files_deploy",
    "files_config", "python_test_files", "ts_test_files", "validator_scripts",
    "workflows", "workflows_on_ready_for_review", "deployment_profile_registry_lines",
    "backend_service_dirs",
)


_BACKEND_DOMAINS = frozenset(("tenancy", "ingestion", "identity", "graph", "journeys", "intelligence", "value", "actions", "governance", "workers", "connectors", "replay", "billing"))


def _tracked_files(root: Path = ROOT) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True
    )
    return [line for line in out.stdout.splitlines() if line]


def _repo_path_problem(path: Any, root: Path = ROOT) -> str | None:
    """Why ``path`` cannot name an entry inside the repository, or None.

    ``root / ""`` is the repository root and ``root / "/tmp"`` discards ``root``,
    so unchecked values could satisfy an existence test without naming anything.
    """
    if not isinstance(path, str) or not path.strip():
        return "must be a non-empty string"
    candidate = Path(path)
    if candidate.is_absolute():
        return "must be relative to the repository root"
    resolved = (root / candidate).resolve()
    base = root.resolve()
    if resolved == base or base not in resolved.parents:
        return "must stay inside the repository"
    return None


def _exists(path: Any, root: Path = ROOT) -> bool:
    return _repo_path_problem(path, root) is None and (root / path).exists()


def _paths(value: Any) -> list[str]:
    return [item for item in value] if isinstance(value, list) else []


def _baseline_errors(baseline: Any) -> list[str]:
    """The recorded measurements ``--report`` compares against must stay complete."""
    if not isinstance(baseline, dict):
        return ["baseline must be a mapping"]
    errors: list[str] = []
    if not isinstance(baseline.get("date"), dt.date):
        errors.append("baseline.date must be an ISO date")
    commit = baseline.get("commit")
    if not (isinstance(commit, str) and commit.strip()):
        errors.append("baseline.commit must be a non-empty string")
    metrics = baseline.get("metrics")
    if not isinstance(metrics, dict):
        return errors + ["baseline.metrics must be a mapping"]
    for key in METRIC_KEYS:
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"baseline.metrics.{key} must be a non-negative integer")
    extra = sorted(set(metrics) - set(METRIC_KEYS))
    if extra:
        errors.append(f"baseline.metrics has metrics measure() does not report: {extra}")
    return errors


def validate(
    path: Path = LEDGER, *, today: dt.date | None = None, root: Path = ROOT
) -> list[str]:
    today = today or dt.date.today()
    errors: list[str] = []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot load debt retirement ledger: {exc}"]
    if not isinstance(raw, dict):
        return ["ledger must be a mapping"]
    if raw.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if raw.get("authority") != "debt-retirement":
        errors.append("authority must be debt-retirement")
    errors.extend(_baseline_errors(raw.get("baseline")))
    entries = raw.get("entries")
    if not isinstance(entries, list) or not entries:
        return errors + ["entries must be a non-empty list"]

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be a mapping")
            continue
        ident = entry.get("id")
        if isinstance(ident, str) and ident.strip():
            where = f"entry {ident!r}"
        else:
            errors.append(f"{where}: id must be a non-empty string")
            ident = None
        for key in REQUIRED:
            if key not in entry:
                errors.append(f"{where}: missing {key}")
        if ident is not None:
            if ident in seen:
                errors.append(f"{where}: duplicate id")
            seen.add(ident)
        for key in TEXT_FIELDS:
            value = entry.get(key)
            if key in entry and not (isinstance(value, str) and value.strip()):
                errors.append(f"{where}: {key} must be a non-empty string")
        if entry.get("domain") not in DOMAINS:
            errors.append(f"{where}: domain must be one of {sorted(DOMAINS)}")
        if entry.get("classification") not in CLASSIFICATIONS:
            errors.append(f"{where}: classification must be one of {sorted(CLASSIFICATIONS)}")
        state = entry.get("state")
        if state not in STATES:
            errors.append(f"{where}: state must be one of {sorted(STATES)}")
        if entry.get("mechanism") not in MECHANISMS:
            errors.append(f"{where}: mechanism must be one of {sorted(MECHANISMS)}")
        for key in ("current", "duplicates", "consumers"):
            if not isinstance(entry.get(key), list):
                errors.append(f"{where}: {key} must be a list of repository paths")

        deadline = entry.get("deadline")
        due: dt.date | None = None
        if isinstance(deadline, dt.date):
            due = deadline
        elif deadline is not None:
            errors.append(f"{where}: deadline must be an ISO date or null")
        if state in {"converge", "deprecated", "deletion-ready"}:
            if due is None:
                errors.append(f"{where}: {state} requires a deadline")
            elif due < today:
                errors.append(
                    f"{where}: deadline {due} has passed; remove it or re-decide it with a new date"
                )

        if state == "retain" and _paths(entry.get("duplicates")):
            errors.append(f"{where}: a retained authority must not list duplicates to retire")
        if state in {"converge", "deprecated", "deletion-ready"} and not (
            _paths(entry.get("duplicates")) or entry.get("retire")
        ):
            errors.append(f"{where}: {state} must name what is retired (duplicates or retire)")

        # A removed row may be recorded straight from a cutover PR, so it must
        # show the same prerequisites as deletion-ready rather than assume it
        # passed through that state.
        if state in {"deletion-ready", "removed"}:
            for key in DELETION_EVIDENCE:
                if not entry.get(key):
                    errors.append(f"{where}: {state} requires {key}")
            if _paths(entry.get("consumers")):
                errors.append(f"{where}: {state} cannot still list consumers")
        if state == "removed":
            removal_pr = entry.get("removal_pr")
            if not (isinstance(removal_pr, str) and removal_pr.strip()):
                errors.append(f"{where}: removed requires removal_pr")
        # Every named path must be a repository path, whatever the state: an
        # absolute or traversing value must not count as proof of absence either.
        for key in ("current", "duplicates", "consumers"):
            for item in _paths(entry.get(key)):
                problem = _repo_path_problem(item, root)
                if problem:
                    errors.append(f"{where}: {key} path {item!r} {problem}")
                elif state == "removed" and key == "duplicates":
                    if _exists(item, root):
                        errors.append(f"{where}: removed but {item} still exists")
                elif state != "removed" and not _exists(item, root):
                    errors.append(f"{where}: {key} path does not exist: {item}")
    return errors


def measure(root: Path = ROOT) -> dict[str, int]:
    files = _tracked_files(root)

    def count(pred) -> int:
        return sum(1 for f in files if pred(f))

    def top(prefix: str) -> int:
        return count(lambda f: f.startswith(prefix))

    workflows = sorted(f for f in files if f.startswith(".github/workflows/") and f.endswith(".yml"))
    on_ready = 0
    for wf in workflows:
        try:
            doc = yaml.safe_load((root / wf).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        on = doc.get(True, doc.get("on")) or {}
        pr = on.get("pull_request") if isinstance(on, dict) else None
        if isinstance(pr, dict) and "ready_for_review" in (pr.get("types") or []):
            on_ready += 1
    profile_files = [
        "config/deployment_profiles.yaml", "config/deploy_profile.yaml",
        "config/deployment_profile_compatibility.yaml", "config/runtime_deployment.yaml",
        "config/environment_requirements.yaml", "config/dependency_profiles.yaml",
    ]
    profile_lines = 0
    for pf in profile_files:
        if (root / pf).exists():
            profile_lines += len((root / pf).read_text(encoding="utf-8").splitlines())
    service_dirs = {
        f.split("/")[3] for f in files
        if f.startswith("services/api/") and f.split("/")[2] in _BACKEND_DOMAINS and f.count("/") >= 4
    }
    return {
        "tracked_files": len(files),
        "files_services": top("services/"),
        "files_frontend": sum(top(f"apps/{name}/") for name in ("aether", "aether-marketing", "demo", "docs", "kyber", "marketing", "olympus-marketing", "shared", "site", "status")),
        "files_tests": top("tests/"),
        "files_docs": top("docs/"),
        "files_docs_archive": top("docs/archive/"),
        "files_packages": top("packages/"),
        "files_scripts": top("scripts/"),
        "files_deploy": top("infra/"),
        "files_config": top("config/"),
        "python_test_files": count(lambda f: f.endswith(".py") and f.rsplit("/", 1)[-1].startswith("test_")),
        "ts_test_files": count(lambda f: f.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))),
        "validator_scripts": count(lambda f: f.startswith("scripts/") and f.rsplit("/", 1)[-1].startswith("validate_") and f.endswith(".py")),
        "workflows": len(workflows),
        "workflows_on_ready_for_review": on_ready,
        "deployment_profile_registry_lines": profile_lines,
        "backend_service_dirs": len(service_dirs),
    }


def report(path: Path = LEDGER, root: Path = ROOT) -> int:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    baseline = (raw.get("baseline") or {}).get("metrics") or {}
    current = measure(root)
    width = max(len(k) for k in current)
    print(f"{'metric'.ljust(width)}  baseline  current  delta")
    for key, value in current.items():
        base = baseline.get(key)
        delta = "" if base is None else f"{value - base:+d}"
        print(f"{key.ljust(width)}  {str(base if base is not None else '-'):>8}  {value:>7}  {delta}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print size metrics vs the baseline")
    parser.add_argument("--json", action="store_true", help="with --report, print current metrics as JSON")
    args = parser.parse_args(argv)
    if args.report:
        if args.json:
            print(json.dumps(measure(), indent=2))
            return 0
        return report()
    errors = validate()
    if errors:
        print("debt retirement ledger: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    raw = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    states: dict[str, int] = {}
    for entry in raw["entries"]:
        states[entry["state"]] = states.get(entry["state"], 0) + 1
    print(f"debt retirement ledger: {len(raw['entries'])} entries OK {dict(sorted(states.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
