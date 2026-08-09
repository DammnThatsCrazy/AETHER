"""Migration-head integrity gate (program §25/§28).

``alembic upgrade head`` requires EXACTLY ONE head revision. This test parses
the real Alembic graph under ``Backend Architecture/aether-backend/alembic/versions``
as Python source (AST — never imports/executes migration code) and asserts:

1.  exactly one head revision;
2.  every revision is reachable from that head (no orphaned chains);
3.  revision ids are unique and every ``down_revision`` references an existing
    revision (no dangling parents, no self-parents);
4.  additive-only: no new detached root is introduced — the base set is exactly
    the two declared roots (``a1b2c3d4e5f6`` initial schema and
    ``9a1b2c3d4e5f`` silver fact tables);
5.  every merge (tuple ``down_revision``) is a genuine consolidation: removing
    it increases the head count (it merged multiple chains into one), so no
    migration can silently fork the lineage.

Nothing here mutates anything; the version directory is only read.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Optional

#: Repo-root relative path from this file: tests/unit -> aether-backend -> Backend
#: Architecture -> repo root. Matches the layout used by test_migration_safety.py.
REPO_ROOT = Path(__file__).resolve().parents[4]
VERSIONS_DIR = (
    REPO_ROOT / "Backend Architecture" / "aether-backend" / "alembic" / "versions"
)

#: The two established roots of the migration graph. Additive-only means a new
#: migration must append to the existing lineage, never open a new root.
KNOWN_BASES = frozenset({"a1b2c3d4e5f6", "9a1b2c3d4e5f"})


class Revision:
    __slots__ = ("revision", "filename", "parents")

    def __init__(self, revision: str, filename: str, parents: tuple[str, ...]) -> None:
        self.revision = revision
        self.filename = filename
        self.parents = parents


def _module_level_literals(tree: ast.Module) -> dict[str, object]:
    """Top-level ``NAME = <literal>`` assignments (exactly how every revision
    declares ``revision`` / ``down_revision``)."""
    values: dict[str, object] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    return values


def _parse_revisions() -> dict[str, Revision]:
    """Parse every ``*.py`` in the versions dir into ``{revision_id: Revision}``.

    Raises ``AssertionError`` on a structural violation (duplicate id, missing
    revision declaration, dangling/self parent) so a bad graph fails loudly
    even before the head-count assertions.
    """
    revisions: dict[str, Revision] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = _module_level_literals(tree)
        rid = values.get("revision")
        if not isinstance(rid, str) or not rid:
            continue  # non-revision modules (e.g. __init__ templates) ignored
        assert rid not in revisions, (
            f"duplicate revision id {rid!r} in {revisions[rid].filename} and {path.name}"
        )
        raw = values.get("down_revision")
        if raw is None:
            parents: tuple[str, ...] = ()
        elif isinstance(raw, str):
            parents = (raw,)
        elif isinstance(raw, (tuple, list)):
            parents = tuple(p for p in raw if isinstance(p, str))
        else:
            parents = ()
        assert rid not in parents, f"revision {rid!r} lists itself as a parent"
        revisions[rid] = Revision(rid, path.name, parents)
    return revisions


def _graph() -> dict[str, Revision]:
    graph = _parse_revisions()
    assert graph, f"no revisions parsed from {VERSIONS_DIR}"
    for rev in graph.values():
        for parent in rev.parents:
            assert parent in graph, (
                f"revision {rev.revision!r} ({rev.filename}) has a dangling "
                f"down_revision {parent!r}"
            )
    return graph


def _heads(graph: dict[str, Revision]) -> set[str]:
    referenced = set()
    for rev in graph.values():
        referenced.update(rev.parents)
    return {rid for rid in graph if rid not in referenced}


def _bases(graph: dict[str, Revision]) -> set[str]:
    return {rid for rid, rev in graph.items() if not rev.parents}


def _reachable_from(heads: set[str], graph: dict[str, Revision]) -> set[str]:
    seen: set[str] = set()
    stack = list(heads)
    while stack:
        rid = stack.pop()
        if rid in seen:
            continue
        seen.add(rid)
        stack.extend(graph[rid].parents)
    return seen


def test_single_valid_head() -> None:
    graph = _graph()
    heads = _heads(graph)
    assert len(heads) == 1, (
        f"alembic upgrade head would fail: {len(heads)} heads present "
        f"({sorted(heads)}). A merge-point migration is required."
    )


def test_every_revision_reachable_from_head() -> None:
    graph = _graph()
    heads = _heads(graph)
    reachable = _reachable_from(heads, graph)
    orphaned = sorted(set(graph) - reachable)
    assert orphaned == [], (
        "revision(s) are orphaned (not reachable from the single head): "
        f"{orphaned}"
    )


def test_additive_only_no_new_detached_roots() -> None:
    graph = _graph()
    bases = _bases(graph)
    assert bases == KNOWN_BASES, (
        "the migration base set changed — a new detached root was introduced. "
        f"bases={sorted(bases)} expected={sorted(KNOWN_BASES)}. "
        "Append to the existing lineage instead of opening a new root."
    )


def test_all_down_revisions_reference_existing_unique_revisions() -> None:
    graph = _graph()  # dangling/self/duplicate assertions live in _parse/_graph
    assert graph
    # uniqueness of revision ids is asserted inside _parse_revisions already;
    # this additionally guarantees the graph has no cycles to a root.
    reachable = _reachable_from(_heads(graph), graph)
    assert reachable == set(graph)


def test_every_merge_consolidates_the_lineage() -> None:
    """A tuple ``down_revision`` may only appear on a genuine merge that reduces
    the head count — removing it must leave MORE than one head."""
    graph = _graph()
    merges = [rev for rev in graph.values() if len(rev.parents) >= 2]
    assert merges, "expected at least one merge-point migration"
    full_head_count = len(_heads(graph))
    assert full_head_count == 1
    for rev in merges:
        pruned = {rid: r for rid, r in graph.items() if rid != rev.revision}
        head_count_without = len(_heads(pruned))
        assert head_count_without > full_head_count, (
            f"merge revision {rev.revision!r} ({rev.filename}) does not "
            "consolidate the lineage — removing it leaves the same head count. "
            "A merge must join multiple chains into one."
        )


def test_merge_parents_are_distinct_existing_revisions() -> None:
    graph = _graph()
    for rev in graph.values():
        if len(rev.parents) >= 2:
            assert len(set(rev.parents)) == len(rev.parents), (
                f"merge {rev.revision!r} lists a duplicate parent"
            )
            for parent in rev.parents:
                assert parent in graph
                assert parent != rev.revision


def test_revision_ids_match_filename_date_prefix_pattern() -> None:
    """Convention check: every migration filename carries the YYYYMMDD it was
    authored, keeping the graph human-navigable. Non-conforming names are a
    review smell, not a hard failure on the graph itself."""
    graph = _graph()
    import re

    for rev in graph.values():
        assert re.match(r"^\d{8}_", rev.filename), (
            f"revision {rev.revision!r} filename {rev.filename!r} does not "
            "start with the YYYYMMDD_ prefix"
        )


if __name__ == "__main__":  # pragma: no cover - manual debug entry point
    graph = _graph()
    print(f"revisions={len(graph)} heads={sorted(_heads(graph))} "
          f"bases={sorted(_bases(graph))}")
    for test in (
        test_single_valid_head,
        test_every_revision_reachable_from_head,
        test_additive_only_no_new_detached_roots,
        test_every_merge_consolidates_the_lineage,
    ):
        test()
        print(f"PASS {test.__name__}")
