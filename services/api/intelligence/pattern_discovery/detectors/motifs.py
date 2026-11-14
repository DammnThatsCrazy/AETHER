"""Novel graph motifs: small typed structures nobody registered.

The relationship spine matches a *catalog* of known motifs
(``relationship-motif-registry.json``). This detector looks for typed
structures that are not in that catalog and are over-represented:

* **Typed triangles.** Over the graph built from extraction (entity
  ``USES_<type>`` attribute, entity ``TRANSACTS_WITH`` / ``DELEGATED_BY`` /
  ``SPAWNED_BY`` / ``INVITED_BY`` / ``TARGETS`` counterparty) plus any
  supplied graph edges. A triangle signature is the sorted set of its typed
  edges. Its *lift* is its closure rate (triangles per open wedge of the same
  two edge types) relative to the graph's global closure rate.
* **Directed cycles** (length 3–4) over relationship edges only (not
  attribute edges): e.g. invite loops, delegation loops, round-trip value.

Signatures whose edge-type set equals a registered motif are skipped; the
deterministic matcher owns those. Hub nodes (degree above ``MAX_DEGREE``) are
not expanded; the shared-attribute detector reports hubs.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from itertools import combinations

from ..extraction import LINKAGE_TYPES
from ..contracts import KIND_NOVEL_MOTIF, EvidenceItem, RawPattern
from .base import DetectorOutput
from .frame import DiscoveryFrame, entity_kinds, plural, risk_categories_for

NAME = "motifs"
MAX_DEGREE = 200
MAX_EDGES = 100_000
MAX_INSTANCES_KEPT = 30
RELATION_TYPES = frozenset({"TRANSACTS_WITH", "DELEGATED_BY", "SPAWNED_BY", "INVITED_BY", "TARGETS"})


def _kind(node: str) -> str:
    return node.split(":", 1)[0]


def _is_attribute(node: str) -> bool:
    k = _kind(node)
    return k in LINKAGE_TYPES or k == "field"


def known_motif_signatures() -> frozenset:
    """Edge-type sets of every registered relationship motif."""
    try:
        from shared.relationship_spine.generated_relationship_motif_registry import RELATIONSHIP_MOTIFS
    except Exception:  # noqa: BLE001 - registry is optional context, never a hard dependency
        return frozenset()
    out = set()
    for motif in RELATIONSHIP_MOTIFS:
        preds = frozenset(str(e.get("predicate")) for e in motif.get("requiredEdges", []) if e.get("predicate"))
        if preds:
            out.add(preds)
    return frozenset(out)


def build_edges(frame: DiscoveryFrame) -> dict[tuple[str, str], str]:
    edges: dict[tuple[str, str], str] = {}
    for ev in frame.events:
        for a in ev.attributes:
            node = f"{a.type.split(':', 1)[0] if not a.type.startswith('field:') else 'field'}:{a.value}"
            edges.setdefault((ev.entity, node), f"USES_{a.type.split(':', 1)[0].upper()}")
        for relation, target in ev.counterparties:
            edges.setdefault((ev.entity, target), relation)
        if len(edges) >= MAX_EDGES:
            break
    for e in frame.external_edges[:MAX_EDGES]:
        s, t, typ = e.get("source"), e.get("target"), e.get("type")
        if not (isinstance(s, str) and isinstance(t, str) and isinstance(typ, str)) or s == t:
            continue
        sk, tk = e.get("source_kind"), e.get("target_kind")
        s = s if ":" in s or not sk else f"{sk}:{s}"
        t = t if ":" in t or not tk else f"{tk}:{t}"
        edges.setdefault((s, t), typ.upper())
    return edges


def _edge_label(s: str, t: str, typ: str) -> str:
    return f"{_kind(s)}-{typ}->{_kind(t)}"


def detect_motifs(frame: DiscoveryFrame) -> DetectorOutput:
    cfg = frame.config
    edges = build_edges(frame)
    if len(edges) < 3:
        return DetectorOutput(NAME, [], {"motif_counts": {}}, {"edges": len(edges), "reported": 0})
    known = frame.known_motif_signatures or known_motif_signatures()
    adj: dict[str, dict[str, str]] = defaultdict(dict)   # undirected neighbour -> edge label
    out_rel: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (s, t), typ in edges.items():
        label = _edge_label(s, t, typ)
        adj[s][t] = label
        adj[t][s] = label
        if typ in RELATION_TYPES or not _is_attribute(t):
            out_rel[s].append((t, typ))

    # Wedge counts per wedge signature (pair of edge labels at a centre).
    wedge_counts: Counter = Counter()
    total_wedges = 0
    for center, nbrs in adj.items():
        if len(nbrs) > MAX_DEGREE:
            continue
        by_label = Counter(nbrs.values())
        labels = sorted(by_label)
        for i, a in enumerate(labels):
            ca = by_label[a]
            wedge_counts[(a, a)] += ca * (ca - 1) // 2
            for b in labels[i + 1:]:
                wedge_counts[(a, b)] += ca * by_label[b]
        d = len(nbrs)
        total_wedges += d * (d - 1) // 2

    order = {n: (len(adj[n]), n) for n in adj}
    tri: dict[tuple[str, ...], list[tuple[str, str, str]]] = defaultdict(list)
    tri_counts: Counter = Counter()
    for u in adj:
        if len(adj[u]) > MAX_DEGREE:
            continue
        higher = [v for v in adj[u] if order[v] > order[u] and len(adj[v]) <= MAX_DEGREE]
        for v, w in combinations(sorted(higher), 2):
            if w in adj[v]:
                labels = tuple(sorted((adj[u][v], adj[u][w], adj[v][w])))
                tri_counts[labels] += 1
                if len(tri[labels]) < MAX_INSTANCES_KEPT:
                    tri[labels].append((u, v, w))
    total_tri = sum(tri_counts.values())
    global_closure = (3 * total_tri / total_wedges) if total_wedges else 0.0

    motif_counts: dict[str, float] = {}
    candidates = []
    for labels, count in tri_counts.items():
        key = "tri|" + "|".join(labels)
        motif_counts[key] = float(count)
        types = frozenset(lbl.split("-")[1].split("->")[0] for lbl in labels)
        if types in known or count < cfg.motif_min_instances:
            continue
        # Closure of this triangle type relative to the graph.
        a, b, c = labels
        wedges = max(wedge_counts.get(tuple(sorted((a, b))), 0) + wedge_counts.get(tuple(sorted((a, c))), 0)
                     + wedge_counts.get(tuple(sorted((b, c))), 0), 1)
        closure = 3 * count / wedges
        lift = closure / global_closure if global_closure > 0 else float("inf")
        if lift < cfg.motif_min_lift:
            continue
        candidates.append(("triangle", labels, count, lift, tri[labels], key))

    # Directed relationship cycles of length 3..4.
    cycles: dict[tuple, list[tuple]] = defaultdict(list)
    cyc_counts: Counter = Counter()
    nodes = sorted(n for n in out_rel if len(out_rel[n]) <= MAX_DEGREE)
    for start in nodes:
        stack = [(start, [start], [])]
        while stack:
            node, path, types = stack.pop()
            for nxt, typ in out_rel.get(node, ()):
                if nxt == start and len(path) >= 3:
                    seq = tuple(f"{_kind(path[i])}-{types[i] if i < len(types) else typ}" for i in range(len(path)))
                    rot = min(seq[i:] + seq[:i] for i in range(len(seq)))
                    inst = tuple(sorted(path))
                    if inst not in {tuple(sorted(x)) for x in cycles[rot]}:
                        cyc_counts[rot] += 1
                        if len(cycles[rot]) < MAX_INSTANCES_KEPT:
                            cycles[rot].append(tuple(path))
                elif nxt not in path and nxt > start and len(path) < 4:
                    stack.append((nxt, path + [nxt], types + [typ]))
    for rot, count in cyc_counts.items():
        key = "cyc|" + "|".join(rot)
        motif_counts[key] = float(count)
        types = frozenset(part.split("-", 1)[1] for part in rot)
        if types in known or count < max(2, cfg.motif_min_instances - 1):
            continue
        candidates.append(("cycle", rot, count, float("inf"), cycles[rot], key))

    prior = frame.baseline.get("motif_rate") or {}
    has_history = int(frame.baseline.get("runs") or 0) > 0
    patterns: list[RawPattern] = []
    candidates.sort(key=lambda c: (-c[2], c[1]))
    for shape, labels, count, lift, instances, key in candidates[: cfg.max_patterns_per_detector]:
        nodes_in = sorted({n for inst in instances for n in inst})
        entities = [n for n in nodes_in if not _is_attribute(n)]
        if len(entities) < 2:
            continue
        attributes = [n for n in nodes_in if _is_attribute(n)]
        usual = prior.get(key)
        novelty = 1.0 if usual is None else max(0.0, (count / max(usual, 1e-9) - 1) / (count / max(usual, 1e-9) + 1))
        if not has_history:
            novelty = 1.0
        relations = sorted({lbl.split("-")[1].split("->")[0] for lbl in labels} if shape == "triangle"
                           else {p.split("-", 1)[1] for p in labels})
        attr_types = sorted({_kind(a) for a in attributes})
        desc = ", ".join(labels)
        lift_txt = f" (closure {lift:.1f}x the graph average)" if math.isfinite(lift) else ""
        patterns.append(RawPattern(
            kind=KIND_NOVEL_MOTIF,
            signature={"shape": shape, "edges": list(labels)},
            title=f"Unregistered {shape} motif: {desc}",
            summary=f"{plural(count, 'instance')} of an unregistered {shape} [{desc}] across "
                    f"{plural(len(entities), 'entity')}{lift_txt}.",
            affected_entities=entities,
            evidence=[
                EvidenceItem("motif_instances", "observed", 0.15, {
                    "shape": shape, "instances": count,
                    "examples": [list(i) for i in instances[:10]],
                    "attribute_nodes": attributes[:20],
                }),
                EvidenceItem("over_represented_structure" if math.isfinite(lift) else "closed_relationship_loop",
                             "inferred", min(0.45, 0.1 * math.log2(lift)) if math.isfinite(lift) else 0.3, {
                                 "lift": round(lift, 2) if math.isfinite(lift) else None,
                                 "global_closure": round(global_closure, 5),
                             }),
                EvidenceItem("not_in_motif_registry", "observed", 0.05, {"edge_types": relations}),
            ],
            occurrence_count=count,
            first_observed_at=None,
            last_observed_at=None,
            risk_categories=risk_categories_for(attr_types=attr_types, entity_kinds=entity_kinds(entities),
                                                relations=relations) + (["relationship"] if shape == "cycle" else []),
            competing_explanations=[
                {"id": "data_model_artifact", "note": "A provider that echoes the same identifier into several fields creates structure that is not behaviour."},
                {"id": "organic_community", "note": "Tight real-world groups (teams, families, communities) close triangles naturally."},
            ],
            novelty=round(novelty, 3),
            baseline={"lift": round(lift, 3) if math.isfinite(lift) else None,
                      "baseline_count": usual, "global_closure": round(global_closure, 5)},
            episode_count=count,
            detector=NAME,
        ))
    for p in patterns:
        p.risk_categories = sorted(set(p.risk_categories))
    return DetectorOutput(NAME, patterns, {"motif_counts": motif_counts}, {
        "edges": len(edges), "triangles": total_tri, "cycles": sum(cyc_counts.values()),
        "known_signatures": len(known), "reported": len(patterns),
    })
