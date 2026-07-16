#!/usr/bin/env python3
"""Validate the storage policy registry — schema, coherence, and coverage.

FT-7-STORAGE-DESCRIPTORS upgraded this gate from the PR-0 seed (schema-only)
to full enforcement:

  1. Schema + coherence (unchanged from the seed gate, never weakened):
     every policy has the required fields, no duplicate resource types,
     delete_behavior is a known value, and legal-retention data can never be
     hard-deleted.

  2. Coverage (new, fail-closed): the persistent-resource inventory is derived
     from the repo itself — BaseRepository-backed store names in
     ``Backend Architecture/aether-backend/repositories/repos.py`` plus every
     table created by ``Backend Architecture/aether-backend/alembic/versions``
     migrations (literal ``CREATE TABLE IF NOT EXISTS`` statements and the
     ``*TABLES*`` list/tuple/dict constants used by loop-style migrations).
     Every inventory entry MUST have a policy, and every policy MUST map to an
     inventory entry (no stale/typo'd policies masking coverage). Adding a new
     repository or migration-created table without a policy fails CI.

  3. Enforcement flag: ``enforcement_status`` must be ``enforced``. Flipping it
     back to ``seed`` does not bypass coverage — coverage always runs.

Usage: python scripts/release/check_storage_policies.py
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402

REQUIRED_FIELDS = [
    "resource_type", "authoritative_store", "metadata_store",
    "projection_stores", "codec", "format", "retention_class",
    "delete_behavior", "legal_hold_supported",
    # FT-7: the full seed schema is now mandatory on every policy.
    "cache_ttl_seconds", "materialization_mode",
    "allow_adaptive_materialization", "allow_object_externalization",
    "allow_historical_table_storage", "requires_consent_invalidation",
    "requires_permission_hash",
]
VALID_DELETE = {"hard_delete", "tombstone", "preserve"}
VALID_CODEC = {"zstd", "none"}

_BACKEND_REL = Path("Backend Architecture") / "aether-backend"
_STORE_RE = re.compile(r'super\(\)\.__init__\(\s*"([A-Za-z_][A-Za-z0-9_]*)"')
_CREATE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)")
_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


def repo_store_names(root: Path) -> set[str]:
    """BaseRepository-backed store names declared in repositories/repos.py."""
    repos_py = root / _BACKEND_REL / "repositories" / "repos.py"
    return set(_STORE_RE.findall(repos_py.read_text(encoding="utf-8")))


def _strings_from_node(node: ast.AST) -> list[str]:
    """String constants inside a list/tuple/set literal, or dict keys."""
    out: list[str] = []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
    elif isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out.append(key.value)
    return out


def alembic_table_names(root: Path) -> set[str]:
    """Tables created by alembic migrations.

    Covers both literal ``CREATE TABLE IF NOT EXISTS <name>`` DDL and the
    loop-style migrations that render ``CREATE TABLE IF NOT EXISTS {table}``
    from a ``TABLES = [...]`` / ``_TABLES = {...}`` constant: any assignment
    whose target name contains "table" contributes its string list items /
    dict keys, filtered to valid table-name shapes.
    """
    names: set[str] = set()
    versions = root / _BACKEND_REL / "alembic" / "versions"
    for path in sorted(versions.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        names.update(_CREATE_RE.findall(text))
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and "table" in target.id.lower():
                    for value in _strings_from_node(node.value):
                        if _TABLE_NAME_RE.match(value):
                            names.add(value)
    return names


def persistent_resource_inventory(root: Path | None = None) -> set[str]:
    """Every persistent resource type the repo actually declares."""
    root = root or repo_root()
    return repo_store_names(root) | alembic_table_names(root)


def check() -> int:
    r = Reporter("STORAGE POLICIES — config/storage_policies.yaml schema + coverage")

    try:
        data = load_yaml("config/storage_policies.yaml")
    except FileNotFoundError:
        r.fail("config/storage_policies.yaml not found")
        return r.finish()

    policies = (data or {}).get("policies", [])
    r.require(isinstance(policies, list) and bool(policies),
              "policies list present", "policies list missing or empty")

    seen: set[str] = set()
    for idx, pol in enumerate(policies or []):
        rt = (pol or {}).get("resource_type", f"#{idx}")
        missing = [f for f in REQUIRED_FIELDS if f not in (pol or {})]
        r.require(not missing, f"{rt}: all policy fields present",
                  f"{rt}: missing fields {missing}")

        if rt in seen:
            r.fail(f"{rt}: duplicate resource_type policy")
        seen.add(rt)

        delete = (pol or {}).get("delete_behavior")
        if delete is not None and delete not in VALID_DELETE:
            r.fail(f"{rt}: invalid delete_behavior {delete!r}")

        codec = (pol or {}).get("codec")
        if codec is not None and codec not in VALID_CODEC:
            r.fail(f"{rt}: invalid codec {codec!r} (must be one of {sorted(VALID_CODEC)})")

        # Legal/audit data must not be hard-deletable.
        if (pol or {}).get("retention_class") == "legal" and delete == "hard_delete":
            r.fail(f"{rt}: legal retention_class cannot use hard_delete")

    # ------------------------------------------------------------------
    # FT-7 enforcement: registry must be flipped to enforced, and coverage
    # runs regardless of the declared status (fail-closed either way).
    # ------------------------------------------------------------------
    status = (data or {}).get("enforcement_status")
    r.require(status == "enforced",
              "enforcement_status is 'enforced'",
              f"enforcement_status must be 'enforced', found {status!r}")

    inventory = persistent_resource_inventory()
    r.require(bool(inventory),
              f"persistent-resource inventory derived ({len(inventory)} types)",
              "persistent-resource inventory came back empty — extractor broken")

    missing_policies = sorted(inventory - seen)
    if missing_policies:
        for name in missing_policies:
            r.fail(f"{name}: persistent resource type has NO storage policy")
    else:
        r.ok("every persistent resource type has a storage policy")

    unknown_policies = sorted(seen - inventory)
    if unknown_policies:
        for name in unknown_policies:
            r.fail(
                f"{name}: policy does not match any persistent resource type "
                "(stale policy or typo — remove or fix it)"
            )
    else:
        r.ok("every policy maps to a real persistent resource type")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
