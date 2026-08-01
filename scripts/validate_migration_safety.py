#!/usr/bin/env python3
"""Migration destructive-change gate for the Alembic revision graph.

Every revision under ``Backend Architecture/aether-backend/alembic/versions``
is parsed as Python *source* (never imported/executed — Alembic need not be
installed, and we never run arbitrary migration code just to lint it). This
validator walks each revision's ``upgrade()`` body — including local helper
functions the module defines and calls from ``upgrade()`` — looking for
destructive schema operations:

  * ``op.drop_column``
  * ``op.drop_table``
  * ``op.drop_constraint``
  * ``op.rename_table``
  * ``op.alter_column(..., nullable=False, ...)`` with no ``server_default``

A destructive migration is only allowed if:

  1. The module declares ``MIGRATION_PHASE = "contract"`` together with
     ``EXPAND_REVISION = "<id>"``, where ``<id>`` is a real revision that is
     a genuine ancestor of this one (found by walking ``down_revision``
     links — including merge points, where ``down_revision`` is a tuple —
     down from this revision), and is not this revision itself; OR
  2. The revision is explicitly grandfathered in
     ``config/migration_safety_allowlist.yaml`` with a ``reason``.

Nothing here does naive substring matching: detection is AST-based, follows
calls from ``upgrade()`` into same-module helper functions (e.g. a
``_drop_columns()`` helper that loops over ``op.drop_column`` calls), and
ancestry is a real graph walk, not "some earlier revision by filename".

Exit codes:
  0  every destructive migration is either a validated expand/contract pair
     or an explicitly grandfathered allowlist entry, and the allowlist
     itself only references real revisions
  1  a new, undeclared destructive migration was found; a declared
     MIGRATION_PHASE="contract" is malformed (missing/self-referential/
     non-ancestor EXPAND_REVISION); or the allowlist references a revision
     that does not exist
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERSIONS_DIR = (
    REPO_ROOT / "Backend Architecture" / "aether-backend" / "alembic" / "versions"
)
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "config" / "migration_safety_allowlist.yaml"

DESTRUCTIVE_ATTRS = {
    "drop_column",
    "drop_table",
    "drop_constraint",
    "rename_table",
    "alter_column",
}


@dataclass(frozen=True)
class DestructiveOp:
    kind: str
    lineno: int
    detail: str = ""

    def __str__(self) -> str:
        detail = f"({self.detail})" if self.detail else ""
        return f"op.{self.kind}{detail} at line {self.lineno}"


@dataclass(frozen=True)
class RevisionInfo:
    path: Path
    revision: str
    down_revisions: tuple[str, ...]
    migration_phase: str | None
    expand_revision: str | None
    destructive_ops: tuple[DestructiveOp, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return _UNRESOLVED


class _Unresolved:
    """Sentinel for module-level assignments we can't literal_eval."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unresolved>"


_UNRESOLVED = _Unresolved()


def _module_level_assignments(tree: ast.Module) -> dict[str, Any]:
    """Map top-level ``NAME = <literal>`` assignments to their values.

    Only simple ``ast.Assign``/``ast.AnnAssign`` nodes with a single
    ``ast.Name`` target and a literal-evaluable RHS are captured — exactly
    the shape every revision in this repo uses for ``revision``,
    ``down_revision``, and the new ``MIGRATION_PHASE``/``EXPAND_REVISION``
    declarations.
    """
    values: dict[str, Any] = {}
    for node in tree.body:
        target: ast.expr | None = None
        rhs: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, rhs = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, rhs = node.target, node.value
        if target is None or rhs is None or not isinstance(target, ast.Name):
            continue
        value = _literal(rhs)
        if value is not _UNRESOLVED:
            values[target.id] = value
    return values


def _normalize_down_revision(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (tuple, list)):
        return tuple(item for item in raw if isinstance(item, str))
    return ()


def _find_op_alias(tree: ast.Module) -> str:
    """Resolve the local name bound to ``alembic.op`` in this module.

    Every revision in this repo uses ``from alembic import op``, but we
    resolve the alias generically (including ``as`` renames and
    ``import alembic.op as op``-style imports) rather than hardcoding the
    string ``"op"``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "alembic":
            for alias in node.names:
                if alias.name == "op":
                    return alias.asname or "op"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("alembic.op",):
                    return alias.asname or "op"
    return "op"


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _local_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }


def _describe_call(node: ast.Call) -> str:
    parts = []
    for arg in node.args[:2]:
        if isinstance(arg, ast.Constant):
            parts.append(repr(arg.value))
    return ", ".join(parts)


def _is_unsafe_alter_column(node: ast.Call) -> bool:
    nullable_false = False
    has_server_default = False
    for kw in node.keywords:
        if (
            kw.arg == "nullable"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
        ):
            nullable_false = True
        if kw.arg == "server_default":
            has_server_default = True
    return nullable_false and not has_server_default


def _collect_destructive(
    fn: ast.FunctionDef,
    local_funcs: dict[str, ast.FunctionDef],
    op_alias: str,
    visited: set[str],
) -> list[DestructiveOp]:
    """Find destructive ``op.*`` calls reachable from ``fn``.

    Walks ``fn``'s body (which already recurses into nested ``with``/``for``/
    ``if``/``try`` blocks via ``ast.walk``) and, whenever it finds a call to a
    *local, module-level* helper function, recurses into that helper's body
    too — so a migration that factors ``op.drop_column`` calls into a
    ``_drop_columns()`` helper and calls it from ``upgrade()`` is still
    caught. ``visited`` prevents re-walking (or infinitely recursing on)
    mutually-recursive helpers.
    """
    results: list[DestructiveOp] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == op_alias
        ):
            attr = func.attr
            if attr not in DESTRUCTIVE_ATTRS:
                continue
            if attr == "alter_column":
                if _is_unsafe_alter_column(node):
                    results.append(
                        DestructiveOp("alter_column", node.lineno, _describe_call(node))
                    )
            else:
                results.append(DestructiveOp(attr, node.lineno, _describe_call(node)))
        elif isinstance(func, ast.Name) and func.id in local_funcs:
            if func.id in visited:
                continue
            visited.add(func.id)
            results.extend(
                _collect_destructive(local_funcs[func.id], local_funcs, op_alias, visited)
            )
    return results


def parse_revision_file(path: Path) -> RevisionInfo | None:
    """Parse one revision module. Returns ``None`` if it declares no
    ``revision`` literal (i.e. it isn't actually an Alembic revision file)."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    assignments = _module_level_assignments(tree)

    revision = assignments.get("revision")
    if not isinstance(revision, str):
        return None

    down_revisions = _normalize_down_revision(assignments.get("down_revision"))

    migration_phase = assignments.get("MIGRATION_PHASE")
    if not isinstance(migration_phase, str):
        migration_phase = None

    expand_revision = assignments.get("EXPAND_REVISION")
    if not isinstance(expand_revision, str):
        expand_revision = None

    op_alias = _find_op_alias(tree)
    local_funcs = _local_functions(tree)
    upgrade_fn = _find_function(tree, "upgrade")

    destructive_ops: list[DestructiveOp] = []
    if upgrade_fn is not None:
        destructive_ops = _collect_destructive(upgrade_fn, local_funcs, op_alias, set())

    return RevisionInfo(
        path=path,
        revision=revision,
        down_revisions=down_revisions,
        migration_phase=migration_phase,
        expand_revision=expand_revision,
        destructive_ops=tuple(destructive_ops),
    )


def parse_all_revisions(versions_dir: Path) -> dict[str, RevisionInfo]:
    infos: dict[str, RevisionInfo] = {}
    for path in sorted(versions_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        info = parse_revision_file(path)
        if info is None:
            continue
        if info.revision in infos:
            raise ValueError(
                f"duplicate revision id {info.revision!r}: "
                f"{path} and {infos[info.revision].path}"
            )
        infos[info.revision] = info
    return infos


# --------------------------------------------------------------------------
# Graph / ancestry
# --------------------------------------------------------------------------


def build_graph(infos: dict[str, RevisionInfo]) -> dict[str, tuple[str, ...]]:
    return {rid: info.down_revisions for rid, info in infos.items()}


def is_ancestor(candidate: str, start: str, graph: dict[str, tuple[str, ...]]) -> bool:
    """True if ``candidate`` is reachable by walking ``down_revision`` links
    down from ``start`` (i.e. ``candidate`` happened at or before ``start``).

    Handles merge points, where ``down_revision`` is a tuple of parents, by
    fanning out to every parent.
    """
    seen: set[str] = set()
    stack = list(graph.get(start, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if node == candidate:
            return True
        stack.extend(graph.get(node, ()))
    return False


# --------------------------------------------------------------------------
# Allowlist
# --------------------------------------------------------------------------


def load_allowlist(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("allowlist", [])
    if not isinstance(entries, list):
        raise ValueError(f"{path}: 'allowlist' key must be a list")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: allowlist entries must be mappings, got {entry!r}")
    return entries


def validate_allowlist_entries(
    entries: list[dict[str, Any]], infos: dict[str, RevisionInfo]
) -> list[str]:
    errors: list[str] = []
    for entry in entries:
        revision = entry.get("revision")
        reason = entry.get("reason")
        if not revision or not isinstance(revision, str):
            errors.append(f"allowlist entry missing a string 'revision': {entry!r}")
            continue
        if not reason or not isinstance(reason, str):
            errors.append(f"allowlist entry {revision!r} is missing a 'reason'")
        if revision not in infos:
            errors.append(
                f"allowlist entry {revision!r} does not match any parsed revision "
                f"(check for typos or a deleted migration)"
            )
    return errors


# --------------------------------------------------------------------------
# Core validation
# --------------------------------------------------------------------------


def validate_revisions(
    infos: dict[str, RevisionInfo], allowlist_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    graph = build_graph(infos)

    for rid in sorted(infos):
        info = infos[rid]
        if not info.destructive_ops:
            continue

        ops_desc = "; ".join(str(op) for op in info.destructive_ops)
        label = f"{rid} ({info.path.name})"

        if info.migration_phase == "contract":
            if not info.expand_revision:
                errors.append(
                    f"{label}: declares MIGRATION_PHASE='contract' but EXPAND_REVISION "
                    f"is not set — destructive op(s): {ops_desc}"
                )
                continue
            if info.expand_revision == rid:
                errors.append(
                    f"{label}: EXPAND_REVISION must not be its own revision "
                    f"({info.expand_revision!r})"
                )
                continue
            if info.expand_revision not in infos:
                errors.append(
                    f"{label}: EXPAND_REVISION {info.expand_revision!r} does not match "
                    f"any revision in the graph"
                )
                continue
            if not is_ancestor(info.expand_revision, rid, graph):
                errors.append(
                    f"{label}: EXPAND_REVISION {info.expand_revision!r} is not an "
                    f"ancestor of {rid} (walked down_revision links and did not find it)"
                )
                continue
            # Valid expand/contract declaration — allowed.
            continue

        if rid in allowlist_ids:
            continue

        errors.append(
            f"{label}: undeclared destructive migration in upgrade(): {ops_desc}. "
            f"Either declare MIGRATION_PHASE='contract' with an EXPAND_REVISION "
            f"pointing at a real ancestor revision, or grandfather {rid!r} in "
            f"config/migration_safety_allowlist.yaml with a reason."
        )

    return errors


def run(versions_dir: Path, allowlist_path: Path) -> tuple[int, list[str], dict[str, RevisionInfo], list[dict[str, Any]]]:
    infos = parse_all_revisions(versions_dir)
    allowlist_entries = load_allowlist(allowlist_path)

    errors = validate_allowlist_entries(allowlist_entries, infos)
    allowlist_ids = {
        e["revision"] for e in allowlist_entries if isinstance(e.get("revision"), str)
    }
    errors.extend(validate_revisions(infos, allowlist_ids))

    return (1 if errors else 0, errors, infos, allowlist_entries)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions-dir",
        type=Path,
        default=DEFAULT_VERSIONS_DIR,
        help="Directory of Alembic revision modules to scan.",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
        help="Path to the grandfathered-destructive-migration allowlist YAML.",
    )
    args = parser.parse_args(argv)

    if not args.versions_dir.is_dir():
        print(f"migration safety gate: versions dir not found: {args.versions_dir}")
        return 1

    exit_code, errors, infos, allowlist_entries = run(args.versions_dir, args.allowlist)

    if errors:
        print(f"migration safety gate: FAIL ({len(errors)} issue(s))")
        for err in errors:
            print(f"  - {err}")
        return 1

    destructive_count = sum(1 for info in infos.values() if info.destructive_ops)
    print(
        f"migration safety gate: OK — {len(infos)} revisions scanned, "
        f"{destructive_count} destructive migration(s) found, "
        f"{len(allowlist_entries)} grandfathered via allowlist"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
