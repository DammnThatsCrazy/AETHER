"""Agent spawn-lineage tree built from source-reported Silver execution facts.

An orchestrator's sub-agent tree is reconstructed from ``agent_subagent_spawned``
rows (``parent_agent_ref`` -> ``child_agent_ref``). Every edge and node keeps the
source event that supports it and is labelled ``source_reported``: an agent
reference is a claim made by the reporting deployment, not a resolved identity,
and says nothing about which human controls it.

The builder is pure so it can be exercised without storage. Traversal is
cycle-safe and bounded in depth and node count; bounds that bite are reported
in ``truncated`` rather than silently dropped.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Optional

SPAWN_EVENT = "agent_subagent_spawned"
TOOL_EVENTS = frozenset({
    "agent_tool_called", "agent_tool_invocation_observed", "agent_tool_observed",
    "agent_tool_call_observed",
})
OUTCOME_EVENTS = frozenset({
    "agent_task_completed", "agent_task_failed", "agent_outcome_recorded",
})
MAX_DEPTH = 8
MAX_NODES = 100
_TOOL_SAMPLE = 20


def _ref(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _spawn_edges(rows: Iterable[dict[str, Any]], tenant_id: str) -> list[dict[str, Any]]:
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("tenant_id") != tenant_id:
            continue
        if (row.get("event_name") or row.get("event_type")) != SPAWN_EVENT:
            continue
        parent = _ref(row.get("parent_agent_ref")) or _ref(row.get("agent_id"))
        child = _ref(row.get("child_agent_ref"))
        if not parent or not child or parent == child:
            continue
        key = (parent, child)
        occurred = str(row.get("occurred_at") or "")
        existing = edges.get(key)
        if existing is None or (occurred and occurred < existing["spawned_at"]):
            edges[key] = {
                "parent": parent,
                "child": child,
                "spawned_at": occurred,
                "source_event_id": row.get("source_event_id"),
                "root_agent_ref": _ref(row.get("root_agent_ref")),
                "parent_run_id": _ref(row.get("parent_run_id")),
                "delegation_id": _ref(row.get("delegation_id")),
                "evidence_status": "source_reported",
            }
    return list(edges.values())


def _rollup(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    tools: dict[str, int] = defaultdict(int)
    runs: set[str] = set()
    outcomes: dict[str, int] = defaultdict(int)
    first = last = ""
    events = 0
    for row in rows:
        events += 1
        occurred = str(row.get("occurred_at") or "")
        if occurred:
            first = occurred if not first or occurred < first else first
            last = occurred if occurred > last else last
        run = _ref(row.get("run_id"))
        if run:
            runs.add(run)
        name = str(row.get("event_name") or row.get("event_type") or "")
        tool = _ref(row.get("tool_name"))
        if tool and (name in TOOL_EVENTS or not name):
            tools[tool] += 1
        if name in OUTCOME_EVENTS:
            outcomes[str(row.get("outcome") or row.get("status") or name)] += 1
    ranked = sorted(tools.items(), key=lambda item: (-item[1], item[0]))
    return {
        "event_count": events,
        "run_count": len(runs),
        "tool_call_count": sum(tools.values()),
        "tools": [{"tool_name": n, "calls": c} for n, c in ranked[:_TOOL_SAMPLE]],
        "outcomes": dict(sorted(outcomes.items())),
        "first_event_at": first or None,
        "last_event_at": last or None,
    }


def build_lineage_tree(
    *,
    tenant_id: str,
    root_agent_ref: str,
    spawn_rows: Iterable[dict[str, Any]],
    activity_rows: Optional[dict[str, list[dict[str, Any]]]] = None,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> dict[str, Any]:
    """Return the orchestrator tree rooted at ``root_agent_ref``."""
    max_depth = max(1, min(max_depth, MAX_DEPTH))
    max_nodes = max(1, min(max_nodes, MAX_NODES))
    activity_rows = activity_rows or {}
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in _spawn_edges(spawn_rows, tenant_id):
        children[edge["parent"]].append(edge)
    for kids in children.values():
        kids.sort(key=lambda e: (e["spawned_at"], e["child"]))

    seen: set[str] = {root_agent_ref}
    truncated: list[str] = []
    cycle_edges: list[dict[str, str]] = []
    flat: list[dict[str, Any]] = []

    def build(ref: str, depth: int, via: Optional[dict[str, Any]]) -> dict[str, Any]:
        node: dict[str, Any] = {
            "agent_ref": ref,
            "depth": depth,
            "spawned_by": via,
            "activity": _rollup(activity_rows.get(ref, [])),
            "children": [],
        }
        flat.append(node)
        for edge in children.get(ref, []):
            child = edge["child"]
            if child in seen:
                cycle_edges.append({"parent": ref, "child": child})
                continue
            if depth >= max_depth:
                if "max_depth" not in truncated:
                    truncated.append("max_depth")
                continue
            if len(seen) >= max_nodes:
                if "max_nodes" not in truncated:
                    truncated.append("max_nodes")
                continue
            seen.add(child)
            node["children"].append(build(child, depth + 1, edge))
        return node

    tree = build(root_agent_ref, 0, None)
    totals = _rollup([])
    totals.update({
        "agent_count": len(flat),
        "max_depth": max((n["depth"] for n in flat), default=0),
        "run_count": sum(n["activity"]["run_count"] for n in flat),
        "tool_call_count": sum(n["activity"]["tool_call_count"] for n in flat),
        "event_count": sum(n["activity"]["event_count"] for n in flat),
    })
    for key in ("tools", "outcomes", "first_event_at", "last_event_at"):
        totals.pop(key, None)
    return {
        "tenant_id": tenant_id,
        "root_agent_ref": root_agent_ref,
        "evidence_status": "source_reported",
        "attribution": "none",
        "attribution_note": (
            "Agent references are reported by their deployments. This tree does "
            "not identify the person or operator controlling any agent."
        ),
        "tree": tree,
        "totals": totals,
        "cycles_ignored": cycle_edges,
        "truncated": truncated,
    }


def agent_refs_in_tree(tree: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    stack = [tree]
    while stack:
        node = stack.pop()
        refs.append(node["agent_ref"])
        stack.extend(reversed(node["children"]))
    return refs
