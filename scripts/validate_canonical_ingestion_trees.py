#!/usr/bin/env python3
"""Canonical ingestion-tree ownership gate (single-owner registration).

The repo currently holds duplicate ingestion stacks: a deployed, authoritative
Python monolith at ``Backend Architecture/aether-backend/`` and two un-deployed
TypeScript duplicates (``Data Ingestion Layer/`` — whose root package.json is
literally named ``aether-backend`` — and ``Data Lake Architecture/``) plus a set
of orphaned dead legacy modules directly under ``Backend Architecture/``. The
canonical architecture is enforced by giving every tree unit exactly one owner
role and freezing that ownership map.

This gate is shrink-only: the committed registry
(``scripts/allowlists/repo_tree_ownership.json``) enumerates every git-tracked
top-level directory and every ``Backend Architecture`` legacy/canonical unit.
A NEW top-level directory or NEW backend orphan unit fails CI until it is routed
into the canonical tree or explicitly registered (with architect review); a
registry entry whose path is no longer in the tree fails CI (remove it only when
the tree unit is genuinely gone). Deprecation edits to the legacy trees are
acknowledged by the repo-consistency ownership map, not by widening this gate.

Roles:
  canonical                 Backend Architecture/aether-backend, packages/*
  deprecated                Data Ingestion Layer, Data Lake Architecture, each
                            orphaned Backend Architecture legacy module (they
                            carry ``deprecated_at`` + ``disposition``)
  house                     every other top-level source directory
  registered-not-deployable Agent Layer (live broker-coupled workers — never
                            canonical, never deprecated)

Usage:
  python scripts/validate_canonical_ingestion_trees.py        # validate (CI gate)
  python scripts/validate_canonical_ingestion_trees.py --seed # rewrite registry
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "scripts" / "allowlists" / "repo_tree_ownership.json"

# Canonical SDK container (packages/*) + the nested canonical backend unit.
_CANONICAL_CONTAINER = "packages"
_CANONICAL_BACKEND = "Backend Architecture/aether-backend"

# The deprecated duplicate stacks + the live-but-not-deployable workers.
_DEPRECATED_ROOT_TREES = ("Data Ingestion Layer", "Data Lake Architecture")
_AGENT_LAYER = "Agent Layer"

# Backend Architecture README carries the deprecation/orphan banner (Ticket C)
# and is a doc, not a code unit; aether-backend is the canonical unit. Hidden
# tooling/config top-level dirs (.github, .claude, ...) are governed by other
# gates and are never candidate ingestion trees, so they are excluded too.
_BACKEND_LEGACY_SKIP = {"Backend Architecture/README.md"}
_VALID_ROLES = {"canonical", "deprecated", "house", "registered-not-deployable"}
_DEPRECATED_FIELDS = ("deprecated_at", "disposition")
# The orphaned modules named by the deprecation program (must match Ticket C).
_DEPRECATED_ORPHAN_DISP = (
    "orphaned dead legacy module under Backend Architecture/. No new code may be "
    "added here; route work into the canonical tree. Physical removal deferred "
    "to a later phase."
)
_DEPRECATED_ROOT_DISP = (
    "un-deployed TypeScript duplicate of the canonical Python monolith "
    "(Backend Architecture/aether-backend). Kept only by version-sync, "
    "runtime-fallback, and temporal-integrity coupling; physical removal "
    "deferred to a later phase. Do not extend."
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)


def tracked_files() -> set[str]:
    """Return every present source path (index + staged + untracked non-ignored)."""
    files: set[str] = set()
    for extra in (["--cached"], ["--others", "--exclude-standard"]):
        proc = _git("ls-files", *extra)
        if proc.returncode == 0:
            files.update(line for line in proc.stdout.splitlines() if line)
    return files


def _top_level_dirs(files: set[str]) -> set[str]:
    """Every visible git-tracked top-level directory (hidden dot-dirs excluded)."""
    dirs: set[str] = set()
    for path in files:
        if "/" not in path:
            continue
        head, _, _ = path.partition("/")
        if head.startswith("."):
            continue
        dirs.add(head)
    return dirs


def _backend_orphan_units(files: set[str]) -> set[str]:
    """Map every tracked backend file outside the canonical unit to its orphan.

    Returns the exact orphaned modules the deprecation program names: the direct
    root-level ``Backend Architecture/*.py`` modules, ``migrations``, ``mnt``,
    and each ``services/{delegation,journey-service,web3}`` subtree. A NEW
    orphaned module appearing here is reported as tracked-but-unregistered.
    """
    units: set[str] = set()
    prefix = "Backend Architecture/"
    for path in files:
        if not path.startswith(prefix):
            continue
        if path in _BACKEND_LEGACY_SKIP or path.startswith(_CANONICAL_BACKEND + "/"):
            continue
        rest = path[len(prefix):]
        if "/" not in rest:
            units.add(path)  # direct root-level file, e.g. auth.py
            continue
        head, _, tail = rest.partition("/")
        if head in {"migrations", "mnt"}:
            units.add(f"{prefix}{head}")
        elif head == "services":
            sub, _, _ = tail.partition("/")
            units.add(f"{prefix}services/{sub}")
        else:
            units.add(f"{prefix}{head}")
    return units


def expected_units(files: set[str]) -> set[str]:
    """Every tree unit that must carry an ownership registration."""
    units = _top_level_dirs(files)
    units.update(_backend_orphan_units(files))
    units.add(_CANONICAL_BACKEND)
    return units


def _present(path: str, files: set[str]) -> bool:
    if path in files:
        return True
    prefix = path + "/"
    return any(f.startswith(prefix) for f in files)


def _role_for(path: str, orphan_units: set[str]) -> str:
    if path == _CANONICAL_CONTAINER or path == _CANONICAL_BACKEND:
        return "canonical"
    if path == _AGENT_LAYER:
        return "registered-not-deployable"
    if path in _DEPRECATED_ROOT_TREES or path in orphan_units:
        return "deprecated"
    return "house"


def _disposition_for(path: str) -> str:
    if path in _DEPRECATED_ROOT_TREES:
        return _DEPRECATED_ROOT_DISP
    return _DEPRECATED_ORPHAN_DISP


def _note_for(path: str, role: str) -> str:
    if role == "canonical":
        if path == _CANONICAL_BACKEND:
            return (
                "deployed authoritative ingestion/lake/silver monolith; build + "
                "ingress evidence references only this tree."
            )
        return "canonical SDK + shared monorepo container (packages/*)."
    if role == "registered-not-deployable":
        return (
            "live broker-coupled Celery workers (Agent Layer); never canonical, "
            "never deprecated."
        )
    if role == "deprecated":
        return _disposition_for(path)
    if path == "Backend Architecture":
        return (
            "umbrella container of the canonical Backend Architecture/aether-backend "
            "and the deprecated orphaned modules (each registered individually)."
        )
    return "monorepo house directory; route new work into canonical trees."


def build_registry() -> list[dict[str, str]]:
    files = tracked_files()
    orphan_units = _backend_orphan_units(files)
    entries: list[dict[str, str]] = []
    for path in sorted(expected_units(files)):
        role = _role_for(path, orphan_units)
        entry: dict[str, str] = {
            "path": path,
            "role": role,
            "owner": "platform@aether",
            "note": _note_for(path, role),
        }
        if role == "deprecated":
            entry["deprecated_at"] = "2026-09-03"
            entry["disposition"] = _disposition_for(path)
        entries.append(entry)
    return entries


def _load_registry() -> list[dict[str, str]]:
    if not REGISTRY.exists():
        return []
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return [entry for entry in data if isinstance(entry, dict) and entry.get("path")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        action="store_true",
        help="rewrite the ownership registry from the current tracked tree",
    )
    args = parser.parse_args()

    if args.seed:
        seeded = build_registry()
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text(json.dumps(seeded, indent=2) + "\n")
        print(f"seeded canonical ingestion-tree ownership registry: {len(seeded)} tree units")
        return 0

    files = tracked_files()
    registry = {entry["path"]: entry for entry in _load_registry()}
    errors: list[str] = []

    # Registered entries must still exist (shrink-only).
    for path, entry in sorted(registry.items()):
        if not _present(path, files):
            errors.append(
                f"registered tree unit no longer present — REMOVE entry (shrink-only): {path}"
            )

    # Role/value hygiene.
    for path, entry in sorted(registry.items()):
        role = entry.get("role")
        if role not in _VALID_ROLES:
            errors.append(
                f"{path}: invalid role {role!r} (expected one of {sorted(_VALID_ROLES)})"
            )
        if path == _AGENT_LAYER and role != "registered-not-deployable":
            errors.append(
                f"{path}: Agent Layer must stay registered-not-deployable "
                "(live broker-coupled workers — never canonical, never deprecated)"
            )
        if role == "deprecated":
            for field in _DEPRECATED_FIELDS:
                if not entry.get(field):
                    errors.append(f"{path}: deprecated entry must carry {field!r}")

    # Every present tree unit must be registered (no new duplicate trees).
    for path in sorted(expected_units(files)):
        if path not in registry:
            errors.append(
                f"tracked tree unit has no single-owner registration: {path}. "
                "Route the work into the canonical tree "
                "(Backend Architecture/aether-backend or packages/*) or register it "
                "in scripts/allowlists/repo_tree_ownership.json with architect review."
            )

    if errors:
        print("CANONICAL INGESTION-TREE OWNERSHIP VIOLATIONS:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "To acknowledge an intended new tree unit, run "
            "python scripts/validate_canonical_ingestion_trees.py --seed and review the diff.",
            file=sys.stderr,
        )
        return 1

    print(
        f"canonical ingestion trees OK: {len(registry)} registered tree units "
        "match the tracked tree (single-owner registration; no new duplicate trees)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
