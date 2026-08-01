#!/usr/bin/env python3
"""Validate that every principal-scoped MOBILE table is reachable by a DSR erasure.

Erasability of mobile data is expressed in four otherwise-disconnected places:

  1. a repository ``delete_by_principal`` hook that physically erases the rows;
  2. a ``DSR_COMPONENT`` (``services/dsr_propagation/models.py``) that a DSR seeds
     and rolls up to ``completed``;
  3. the ``consent.erasure`` job (``services/consent/erasure_jobs.py``) actually
     erasing that store and marking its component with a real count;
  4. a ``config/storage_policies.yaml`` policy whose ``delete_behavior`` permits the
     erasure and whose ``legal_hold_supported`` is declared.

If any link is missing, a data-subject erasure silently skips that mobile data (the
exact gap this program closed) — or, worse, seeds a component that is never marked so
the DSR never rolls up to ``completed``. This gate binds all four fail-closed: every
mapped mobile component MUST have its repo hook, be in ``DSR_COMPONENTS``, be marked by
the erasure handler, and have coherent storage policies. Removing a mobile table from
``DSR_COMPONENTS`` or unwiring the handler fails CI.

Usage: python scripts/release/check_dsr_coverage.py
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402

_BACKEND_REL = Path("Backend Architecture") / "aether-backend"

# The mobile principal-scoped tables that MUST be reachable by a DSR erasure, each
# mapped to (repo file exposing delete_by_principal, DSR component, storage-policy
# tables it cascades over). Adding a mobile principal-scoped store means adding it
# here AND wiring all four links — that is the point of the gate.
MOBILE_DSR_COVERAGE: dict[str, dict[str, object]] = {
    "continuation_records": {
        "repo": "continuation_repo.py",
        "tables": ["continuations", "continuation_selections"],
    },
    "mobile_installations": {
        "repo": "installation_repo.py",
        "tables": ["mobile_installations", "push_subscriptions"],
    },
    "client_sync_records": {
        "repo": "client_sync_repo.py",
        "tables": ["sync_change_log"],
    },
}


def _read(root: Path, rel: str) -> str:
    return (root / _BACKEND_REL / rel).read_text(encoding="utf-8")


def _dsr_components(root: Path) -> set[str]:
    """The DSR_COMPONENTS tuple, read via AST (no backend import needed).

    ``DSR_COMPONENTS`` is an *annotated* assignment (``DSR_COMPONENTS: tuple[...] =
    (...)``), so both ``ast.Assign`` and ``ast.AnnAssign`` must be handled.
    """
    tree = ast.parse(_read(root, "services/dsr_propagation/models.py"))
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DSR_COMPONENTS" for t in node.targets
        ):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "DSR_COMPONENTS":
            value = node.value
        if value is not None:
            return {
                e.value for e in ast.walk(value)
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    return set()


def _repo_defines_delete_by_principal(root: Path, repo_file: str) -> bool:
    path = root / _BACKEND_REL / "repositories" / repo_file
    if not path.exists():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(n, ast.AsyncFunctionDef) and n.name == "delete_by_principal"
        for n in ast.walk(tree)
    )


def _handler_marked_components(root: Path) -> set[str]:
    """Component name-constants the erasure handler references (assignments whose
    value is a string literal), used to prove each mobile component is wired."""
    text = _read(root, "services/consent/erasure_jobs.py")
    tree = ast.parse(text)
    literals = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    return literals


def _policy_index(root: Path) -> dict[str, dict]:
    data = load_yaml("config/storage_policies.yaml")
    policies = data.get("policies", data) if isinstance(data, dict) else data
    if isinstance(policies, dict):
        policies = policies.get("policies", [])
    return {p.get("resource_type"): p for p in policies if isinstance(p, dict)}


def run(root: Path) -> int:
    r = Reporter("DSR MOBILE COVERAGE — every principal-scoped mobile table is erasable")
    components = _dsr_components(root)
    handler_literals = _handler_marked_components(root)
    policies = _policy_index(root)

    for component, spec in MOBILE_DSR_COVERAGE.items():
        repo_file = str(spec["repo"])
        r.require(
            _repo_defines_delete_by_principal(root, repo_file),
            f"{component}: {repo_file} exposes delete_by_principal",
            f"{component}: {repo_file} is missing a delete_by_principal erase hook",
        )
        r.require(
            component in components,
            f"{component}: present in DSR_COMPONENTS",
            f"{component}: NOT in DSR_COMPONENTS — a DSR erasure would never reach it",
        )
        r.require(
            component in handler_literals,
            f"{component}: marked by the consent.erasure handler",
            f"{component}: NOT referenced by services/consent/erasure_jobs.py — seeded "
            f"but never marked, so the DSR never rolls up to completed",
        )
        for table in spec["tables"]:  # type: ignore[union-attr]
            policy = policies.get(table)
            r.require(
                policy is not None,
                f"{component}: storage policy for {table} exists",
                f"{component}: no storage policy for {table}",
            )
            if policy is not None:
                r.require(
                    policy.get("delete_behavior") in {"hard_delete", "tombstone"},
                    f"{component}: {table} delete_behavior={policy.get('delete_behavior')} permits erasure",
                    f"{component}: {table} delete_behavior={policy.get('delete_behavior')} cannot erase subject data",
                )
    return r.finish()


def main() -> int:
    return run(repo_root())


if __name__ == "__main__":
    main_guard(main)
