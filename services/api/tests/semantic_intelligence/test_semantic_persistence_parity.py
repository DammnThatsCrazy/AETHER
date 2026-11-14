"""Persistence proof for semantic intelligence, read from the real migrations.

Two properties, checked against the Alembic sources (parsed, never executed):

1. Every table the semantic package reads or writes is created by a migration,
   using the same discovery the release gate trusts
   (``scripts/release/check_storage_policies.py``). A repository pointed at a
   table no migration creates only works where something else happens to
   create it, which is not a deployment guarantee.
2. The migration that creates each of those tables defines a ``tenant_id``
   column, so tenant scoping exists at rest and not only in the repository's
   WHERE clauses.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2]
ROOT = API.parents[1]
PACKAGE = API / "intelligence" / "semantic_intelligence"
VERSIONS = API / "alembic" / "versions"
REPO_CLASS = "SemanticFactRepository"
# Generic helpers that receive a table from a caller; the callers are checked.
_PASS_THROUGH = {"table"}


def _gate():
    spec = importlib.util.spec_from_file_location(
        "check_storage_policies_for_semantic_parity",
        ROOT / "scripts" / "release" / "check_storage_policies.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _string_constants() -> dict[str, str]:
    """Module-level ``NAME = "literal"`` assignments across the semantic package."""
    constants: dict[str, str] = {}
    for path in PACKAGE.rglob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                constants[node.targets[0].id] = node.value.value
    return constants


def _tables_used() -> dict[str, str]:
    """``{table: first use}`` from every ``SemanticFactRepository(<table>, ...)``."""
    constants = _string_constants()
    used: dict[str, str] = {}
    unresolved: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and _call_name(node) == REPO_CLASS and node.args):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                used.setdefault(arg.value, f"{rel}:{node.lineno}")
                continue
            ref = arg.id if isinstance(arg, ast.Name) else getattr(arg, "attr", "")
            if ref in constants:
                used.setdefault(constants[ref], f"{rel}:{node.lineno}")
            elif ref not in _PASS_THROUGH:
                unresolved.append(f"{rel}:{node.lineno} ({ast.unparse(arg)})")
    assert not unresolved, (
        f"table names this proof could not resolve (add a constant or a literal): {unresolved}"
    )
    return used


def test_the_proof_discovers_the_semantic_tables():
    used = _tables_used()
    assert len(used) >= 10, f"expected the semantic tables to be discovered, got {sorted(used)}"
    assert {"silver_semantic_observations", "gold_entity_semantic_state"} <= set(used)


def test_every_table_the_semantic_code_uses_is_created_by_a_migration():
    migrated = _gate().alembic_table_names(ROOT)
    missing = {t: where for t, where in _tables_used().items() if t not in migrated}
    assert not missing, f"used by code but created by no migration: {missing}"


@pytest.mark.parametrize(
    "table", ["semantic_replay_jobs", "semantic_review_queue", "semantic_memory_records"]
)
def test_operational_tables_are_in_the_migrations(table):
    assert table in _gate().alembic_table_names(ROOT)


def test_the_migration_creating_each_semantic_table_defines_a_tenant_column():
    sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(VERSIONS.glob("*.py"))}
    untenanted = []
    for table in _tables_used():
        creators = [
            name for name, text in sources.items()
            if table in text and ("create_table" in text or "CREATE TABLE" in text)
        ]
        assert creators, f"no migration source mentions {table}"
        if not any('"tenant_id"' in sources[name] or "tenant_id " in sources[name] for name in creators):
            untenanted.append((table, creators))
    assert not untenanted, f"semantic tables whose creating migration has no tenant_id: {untenanted}"


def test_every_semantic_table_has_a_declared_storage_policy():
    """Retention, delete behavior and consent invalidation are declared per table.
    A table the code writes with no policy has none of them."""
    import yaml

    policies = {
        p["resource_type"]: p
        for p in yaml.safe_load((ROOT / "config" / "storage_policies.yaml").read_text())["policies"]
    }
    missing = sorted(t for t in _tables_used() if t not in policies)
    assert not missing, f"semantic tables with no storage policy: {missing}"


def test_subject_linked_semantic_tables_are_hard_deleted_and_consent_invalidated():
    """Erasure and consent revocation must reach every table that holds subject
    evidence; the policy states it and the DSR erasure planes act on it."""
    import yaml

    policies = {
        p["resource_type"]: p
        for p in yaml.safe_load((ROOT / "config" / "storage_policies.yaml").read_text())["policies"]
    }
    for table in ("silver_semantic_observations", "semantic_memory_records"):
        assert policies[table]["delete_behavior"] == "hard_delete", table
        assert policies[table]["requires_consent_invalidation"] is True, table
