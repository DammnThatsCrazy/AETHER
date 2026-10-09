#!/usr/bin/env python3
"""Validate that every backend service directory has one lifecycle class.

``config/service_classification.yaml`` is the registry. A directory under
``services/backend/services`` with no entry, an entry with no directory, an
unknown class or stage, or a ``deprecated`` service with no row in
``config/debt_retirement_ledger.yaml`` fails validation. ``--report`` prints the
count per class.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/service_classification.yaml"
LEDGER = ROOT / "config/debt_retirement_ledger.yaml"

CLASSES = {"core", "beta", "experimental", "internal", "deprecated", "archived", "removed"}
STAGES = {
    "tenant", "intake", "evidence", "normalization", "resolution", "graph",
    "intelligence", "explanation", "action", "outcome", "control-plane", "product",
}


ROOT_RELATIVE = "services/backend/services"


def service_dirs(root: Path) -> set[str]:
    """Directories that hold Python source; a stray cache-only directory is not a service."""
    base = root / ROOT_RELATIVE
    return {
        p.name for p in base.iterdir()
        if p.is_dir()
        and not p.name.startswith(("__", "."))
        and next(p.rglob("*.py"), None) is not None
    }


def _ledger_paths(ledger: Path) -> set[str]:
    try:
        raw = yaml.safe_load(ledger.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return set()
    paths: set[str] = set()
    entries = raw.get("entries") if isinstance(raw, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        for key in ("current", "duplicates"):
            value = entry.get(key)
            paths.update(p.strip().rstrip("/") for p in (value if isinstance(value, list) else []) if isinstance(p, str))
    return paths


def validate(
    registry: Path = REGISTRY, ledger: Path = LEDGER, root: Path = ROOT
) -> list[str]:
    errors: list[str] = []
    try:
        raw: Any = yaml.safe_load(registry.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot load service classification: {exc}"]
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return ["schema_version must be 1"]
    if raw.get("authority") != "service-classification":
        errors.append("authority must be service-classification")
    if raw.get("root") != ROOT_RELATIVE:
        errors.append(f"root must be {ROOT_RELATIVE!r}, got {raw.get('root')!r}")
    services = raw.get("services")
    if not isinstance(services, dict) or not services:
        return errors + ["services must be a non-empty mapping"]
    bad_names = [n for n in services if not (isinstance(n, str) and n.strip() and "/" not in n)]
    if bad_names:
        errors.append(f"service names must be directory names (non-empty strings): {bad_names!r}")
    services = {n: e for n, e in services.items() if n not in bad_names}

    on_disk = service_dirs(root)
    for name in sorted(on_disk - set(services)):
        errors.append(f"{name}: backend service directory has no classification")
    ledger_paths = _ledger_paths(ledger)
    for name, entry in sorted(services.items()):
        if not isinstance(entry, dict):
            errors.append(f"{name}: entry must be a mapping")
            continue
        cls = entry.get("class")
        if cls not in CLASSES:
            errors.append(f"{name}: class must be one of {sorted(CLASSES)}")
        if entry.get("stage") not in STAGES:
            errors.append(f"{name}: stage must be one of {sorted(STAGES)}")
        reason = entry.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            errors.append(f"{name}: reason is required")
        if cls == "removed":
            if name in on_disk:
                errors.append(f"{name}: classified removed but the directory still exists")
            continue
        if name not in on_disk:
            errors.append(f"{name}: classified but the directory does not exist (use class removed)")
        if cls == "deprecated" and f"{ROOT_RELATIVE}/{name}" not in ledger_paths:
            errors.append(
                f"{name}: deprecated services need a row in the debt retirement ledger "
                f"naming {ROOT_RELATIVE}/{name}"
            )
    return errors


def report(registry: Path = REGISTRY) -> int:
    raw = yaml.safe_load(registry.read_text(encoding="utf-8"))
    counts = Counter(v["class"] for v in raw["services"].values())
    stages = Counter(v["stage"] for v in raw["services"].values())
    print(f"status: {raw.get('status')}")
    print("class         count")
    for cls in ("core", "beta", "experimental", "internal", "deprecated", "archived", "removed"):
        print(f"{cls:<13} {counts.get(cls, 0):>5}")
    print(f"total         {sum(counts.values()):>5}")
    print("stage         count")
    for stage, n in sorted(stages.items()):
        print(f"{stage:<13} {n:>5}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print counts per class and stage")
    args = parser.parse_args(argv)
    if args.report:
        return report()
    errors = validate()
    if errors:
        print("service classification: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    raw = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    print(f"service classification: {len(raw['services'])} services OK (status: {raw.get('status')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
