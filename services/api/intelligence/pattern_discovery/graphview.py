"""Patterns on the graph: one pattern's subgraph, and an overlay for a graph view.

* :func:`pattern_subgraph` turns a pattern record into a small renderable
  graph: the pattern node, its member entities, the shared attribute values
  and counterparties its evidence names (hashed values stay hashed), and the
  links between them (membership, shared attribute use, motif / cycle edges,
  agent principals). Cytoscape-style ``{nodes, edges}``.
* :func:`overlay` answers "which patterns touch the nodes I am looking at?"
  for a graph view: per node id, the visible patterns it belongs to, plus
  the pattern list, so the graph explorer can badge and highlight members.

Graph node ids in the explorer are bare ids; pattern members are ``kind:id``
keys, so both forms are matched.
"""
from __future__ import annotations

from typing import Any

from .contracts import VISIBLE_STATUSES

ENTITY_KINDS = ("user", "entity", "agent", "anon", "session", "wallet")
MAX_NODES = 300


def keys_for_ids(ids: list[str]) -> dict[str, str]:
    """Pattern entity keys to look up for raw graph ids: ``key -> raw id``."""
    out: dict[str, str] = {}
    for raw in ids:
        raw = str(raw).strip()
        if not raw:
            continue
        if ":" in raw and raw.split(":", 1)[0] in ENTITY_KINDS:
            out[raw] = raw
            raw_id = raw.split(":", 1)[1]
            for kind in ENTITY_KINDS:
                out.setdefault(f"{kind}:{raw_id}", raw)
        else:
            for kind in ENTITY_KINDS:
                out.setdefault(f"{kind}:{raw}", raw)
    return out


def _node(nodes: dict[str, dict[str, Any]], nid: str, *, kind: str, label: str, role: str) -> None:
    if nid not in nodes and len(nodes) < MAX_NODES:
        nodes[nid] = {"id": nid, "kind": kind, "label": label[:80], "role": role}


def pattern_subgraph(pattern: dict[str, Any]) -> dict[str, Any]:
    pid = pattern["pattern_id"]
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def edge(source: str, target: str, etype: str) -> None:
        key = (source, target, etype)
        if source in nodes and target in nodes and key not in seen_edges:
            seen_edges.add(key)
            edges.append({"source": source, "target": target, "type": etype})

    _node(nodes, pid, kind="pattern", label=pattern.get("display_title") or pattern.get("title") or pid, role="pattern")
    members = list(pattern.get("affected_entity_keys") or [])
    for key in members:
        kind, _, ident = key.partition(":")
        _node(nodes, key, kind=kind or "entity", label=ident or key, role="member")
        edge(key, pid, "MEMBER_OF_PATTERN")
    member_set = set(members)
    for ev in pattern.get("evidence") or []:
        detail = ev.get("detail") or {}
        etype = ev.get("type")
        if etype == "shared_attribute_values":
            for attr in detail.get("attributes") or []:
                aid = f"{attr.get('type')}:{attr.get('value')}"
                _node(nodes, aid, kind=str(attr.get("type")), label=str(attr.get("value")), role="attribute")
                for m in members:
                    edge(m, aid, f"USES_{str(attr.get('type')).split(':', 1)[0].upper()}")
        elif etype == "motif_instances":
            for inst in detail.get("examples") or []:
                inst = [n for n in inst if isinstance(n, str)]
                for n in inst:
                    kind = n.split(":", 1)[0]
                    _node(nodes, n, kind=kind, label=n.split(":", 1)[-1],
                          role="member" if n in member_set else "attribute")
                for a, b in zip(inst, inst[1:] + inst[:1]):
                    edge(a, b, "MOTIF_LINK")
        elif etype in ("cross_principal_reuse", "cross_principal_ring"):
            for principal in detail.get("principals") or []:
                _node(nodes, principal, kind=principal.split(":", 1)[0], label=principal.split(":", 1)[-1],
                      role="principal")
                for m in members:
                    if m.startswith("agent:"):
                        edge(m, principal, "ACTS_FOR")
        elif etype == "agent_to_agent_links":
            agents = [a for a in detail.get("agents") or [] if isinstance(a, str)]
            for a, b in zip(agents, agents[1:]):
                edge(a, b, "INTERACTS_WITH")
        elif etype == "independent_detector_agreement":
            for m in detail.get("members") or []:
                mid = m.get("pattern_id")
                if mid:
                    _node(nodes, mid, kind="pattern", label=str(m.get("title") or mid), role="member_pattern")
                    edge(mid, pid, "PART_OF")
    return {
        "pattern_id": pid,
        "kind": pattern.get("kind"),
        "title": pattern.get("display_title") or pattern.get("title"),
        "nodes": list(nodes.values()),
        "edges": edges,
        "truncated": len(nodes) >= MAX_NODES or bool(pattern.get("affected_entities_truncated")),
        "claim_state": "inferred",
    }


def overlay(ids: list[str], patterns: list[dict[str, Any]]) -> dict[str, Any]:
    lookup = keys_for_ids(ids)
    by_node: dict[str, list[str]] = {}
    listed: dict[str, dict[str, Any]] = {}
    for p in patterns:
        if p.get("status") not in VISIBLE_STATUSES:
            continue
        hit = False
        for key in p.get("affected_entity_keys") or []:
            raw = lookup.get(key)
            if raw is not None:
                by_node.setdefault(raw, [])
                if p["pattern_id"] not in by_node[raw]:
                    by_node[raw].append(p["pattern_id"])
                hit = True
        if hit:
            listed[p["pattern_id"]] = {
                "pattern_id": p["pattern_id"], "kind": p.get("kind"),
                "title": p.get("display_title") or p.get("title"), "severity": p.get("severity"),
                "status": p.get("status"), "pinned": p.get("pinned"), "surfaced_at": p.get("surfaced_at"),
                "members_in_view": sorted({lookup[k] for k in p.get("affected_entity_keys") or [] if k in lookup}),
                "affected_entity_count": p.get("affected_entity_count"),
            }
    ordered = sorted(listed.values(), key=lambda r: (not r.get("pinned"), -len(r["members_in_view"]), r["pattern_id"]))
    return {"by_node": by_node, "patterns": ordered, "claim_state": "inferred"}
