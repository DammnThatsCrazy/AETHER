"""Agent-specific discovery: spawning, tool-call signatures, agent-to-agent rings.

Three detectors over agent activity (entities ``agent:*``):

* **Spawn anomalies** (``agent_spawn_anomaly``). Sub-agent counts per parent
  (``SPAWNED_BY`` links from children) scored with a robust z against the
  tenant's agent population, plus spawn bursts (many children inside a short
  window). Large fan-out by itself is common; extreme fan-out relative to
  peers, or a burst, is what is reported.
* **Tool-call signatures** (``agent_tool_signature``). The ordered set of
  tools an agent calls in a session forms its signature. A signature shared
  by agents acting for *different* principals is reported: one playbook
  running under many unrelated people is the agent analogue of a fraud ring
  (or of a popular template, which is attached as a competing explanation).
* **Agent interaction clusters** (``agent_interaction_cluster``). Agents that
  transact with, target or message other agents, grouped into connected
  components that span several principals.

Every output is circumstantial; the person link, when any, is the observed
principal, and "the principal may be a victim" is always attached.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from ..contracts import (
    KIND_AGENT_INTERACTION, KIND_AGENT_SPAWN, KIND_AGENT_TOOL_SIGNATURE, EvidenceItem, RawPattern,
)
from .attributes import _UnionFind
from .base import DetectorOutput
from .frame import DiscoveryFrame, bounds, event_refs, plural, risk_categories_for, robust_stats

NAME = "agents"
SPAWN_Z = 5.0
SPAWN_BURST_WINDOW = timedelta(minutes=2)
SPAWN_BURST_MIN = 5
MIN_SIGNATURE_TOOLS = 2
MIN_PRINCIPALS = 2

_VICTIM = {"id": "principal_may_be_a_victim",
           "note": "Delegation shows authority was granted, not intent; a principal may be the victim of a hijacked or over-scoped agent."}


def _principals(frame: DiscoveryFrame) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for e in frame.events:
        if e.entity.startswith("agent:"):
            if e.principal:
                out[e.entity].add(e.principal)
            for rel, target in e.counterparties:
                if rel == "DELEGATED_BY" and not target.startswith("agent:"):
                    out[e.entity].add(target)
    return out


def detect_agents(frame: DiscoveryFrame) -> DetectorOutput:
    cfg = frame.config
    if not any(e.entity.startswith("agent:") for e in frame.events):
        return DetectorOutput(NAME, [], {}, {"agents": 0, "reported": 0})
    principals = _principals(frame)
    patterns: list[RawPattern] = []

    # ── Spawn anomalies ─────────────────────────────────────────────────────
    children: dict[str, dict[str, object]] = defaultdict(dict)  # parent -> child -> first event
    for e in frame.events:
        for rel, target in e.counterparties:
            if rel == "SPAWNED_BY" and target.startswith("agent:") and e.entity != target:
                if e.entity not in children[target] or (e.ts and children[target][e.entity].ts and e.ts < children[target][e.entity].ts):
                    children[target][e.entity] = e
    agent_entities = {e.entity for e in frame.events if e.entity.startswith("agent:")} | set(children)
    counts = {a: len(children.get(a, {})) for a in agent_entities}
    spawned = 0
    if len(counts) >= 10:
        med, sigma = robust_stats([float(c) for c in counts.values()])
        for parent, kids in sorted(children.items()):
            n = len(kids)
            z = (n - med) / sigma
            stamps = sorted(k.ts for k in kids.values() if k.ts)
            burst = 0
            for i, start in enumerate(stamps):
                burst = max(burst, sum(1 for t in stamps[i:] if t - start <= SPAWN_BURST_WINDOW))
            if not (z >= SPAWN_Z and n >= 5) and burst < SPAWN_BURST_MIN:
                continue
            spawned += 1
            evs = list(kids.values())
            first, last = bounds(evs)
            ents = sorted({parent, *kids})
            prin = sorted(principals.get(parent, set()))
            evidence = [EvidenceItem("observed_spawns", "observed", 0.2,
                                     {"parent": parent, "children": n}, event_refs(evs))]
            if z >= SPAWN_Z:
                evidence.append(EvidenceItem("extreme_fan_out", "inferred", min(0.4, 0.04 * z),
                                             {"robust_z": round(z, 2), "agent_population_median": round(med, 2)}))
            if burst >= SPAWN_BURST_MIN:
                evidence.append(EvidenceItem("spawn_burst", "inferred", min(0.35, 0.05 * burst),
                                             {"children_within_window": burst,
                                              "window_seconds": int(SPAWN_BURST_WINDOW.total_seconds())}))
            patterns.append(RawPattern(
                kind=KIND_AGENT_SPAWN,
                signature={"parent": parent},
                title=f"Sub-agent spawning anomaly at {parent}",
                summary=(f"{parent} spawned {plural(n, 'sub-agent')}"
                         + (f" ({burst} within {int(SPAWN_BURST_WINDOW.total_seconds())} s)" if burst >= SPAWN_BURST_MIN else "")
                         + (f", robust z {z:.1f} against {len(counts)} agents" if z >= SPAWN_Z else "")
                         + (f"; principals: {', '.join(prin[:3])}" if prin else "; no principal observed") + "."),
                affected_entities=ents,
                evidence=evidence,
                occurrence_count=n,
                first_observed_at=first,
                last_observed_at=last,
                risk_categories=["agentic", "execution"],
                competing_explanations=[
                    {"id": "legitimate_parallel_workflow", "note": "Orchestrators fanning out parallel workers is normal behaviour."},
                    _VICTIM,
                ],
                novelty=1.0,
                baseline={"robust_z": round(z, 2), "median_children": round(med, 2), "burst": burst},
                episode_count=n,
                detector=NAME,
            ))

    # ── Tool-call signatures shared across principals ──────────────────────
    sig_agents: dict[tuple[str, ...], set[str]] = defaultdict(set)
    sig_events: dict[tuple[str, ...], list] = defaultdict(list)
    for entity, sessions in frame.sessions().items():
        if not entity.startswith("agent:"):
            continue
        for s in sessions:
            tools = tuple(dict.fromkeys(e.tool for e in s if e.tool))
            if len(tools) >= MIN_SIGNATURE_TOOLS:
                sig_agents[tools].add(entity)
                if len(sig_events[tools]) < 60:
                    sig_events[tools].append(s[0])
    tool_patterns = 0
    for tools, ags in sorted(sig_agents.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(ags) < cfg.min_support:
            continue
        prin = set().union(*(principals.get(a, set()) for a in ags))
        if len(prin) < MIN_PRINCIPALS:
            continue
        if not frame.entities_share_ok(len(ags)):
            continue
        tool_patterns += 1
        evs = sig_events[tools]
        first, last = bounds(evs)
        patterns.append(RawPattern(
            kind=KIND_AGENT_TOOL_SIGNATURE,
            signature={"tools": list(tools)},
            title=f"Shared tool-call signature across {plural(len(prin), 'principal')}",
            summary=(f"{plural(len(ags), 'agent')} acting for {plural(len(prin), 'principal')} ran the same "
                     f"tool sequence: {' → '.join(tools[:8])}."),
            affected_entities=sorted(ags | prin),
            evidence=[
                EvidenceItem("identical_tool_sequence", "observed", 0.2,
                             {"tools": list(tools), "agents": len(ags)}, event_refs(evs)),
                EvidenceItem("cross_principal_reuse", "inferred", min(0.45, 0.1 * len(prin)),
                             {"principals": sorted(prin)[:20], "principal_count": len(prin)}),
            ],
            occurrence_count=len(evs),
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=sorted(set(risk_categories_for(tokens=[f"tool:{t}" for t in tools])) | {"agentic"}),
            competing_explanations=[
                {"id": "same_vendor_template", "note": "Independent deployments of one vendor template run identical tool sequences."},
                _VICTIM,
            ],
            novelty=1.0,
            baseline={"agents": len(ags), "principals": len(prin)},
            episode_count=len(evs),
            detector=NAME,
            ))
        if tool_patterns >= cfg.max_patterns_per_detector:
            break

    # ── Agent-to-agent interaction clusters ────────────────────────────────
    uf = _UnionFind()
    link_events: dict[str, list] = defaultdict(list)
    relations: Counter = Counter()
    for e in frame.events:
        if not e.entity.startswith("agent:"):
            continue
        for rel, target in e.counterparties:
            if target.startswith("agent:") and target != e.entity and rel not in ("SPAWNED_BY", "DELEGATED_BY"):
                uf.union(e.entity, target)
                relations[rel] += 1
                link_events[e.entity].append(e)
    groups: dict[str, set[str]] = defaultdict(set)
    for a in uf.parent:
        groups[uf.find(a)].add(a)
    clusters = 0
    for members in sorted(groups.values(), key=lambda g: (-len(g), sorted(g))):
        if len(members) < cfg.min_cluster:
            continue
        prin = set().union(*(principals.get(a, set()) for a in members))
        if len(prin) < MIN_PRINCIPALS:
            continue
        clusters += 1
        evs = [ev for a in members for ev in link_events.get(a, [])]
        first, last = bounds(evs)
        patterns.append(RawPattern(
            kind=KIND_AGENT_INTERACTION,
            signature={"agents": sorted(members)[:10], "relations": sorted(relations)},
            title=f"{plural(len(members), 'agent')} interacting across {plural(len(prin), 'principal')}",
            summary=(f"{plural(len(members), 'agent')} acting for {plural(len(prin), 'different principal')} "
                     f"transact with, target or message each other ({', '.join(sorted(relations))})."),
            affected_entities=sorted(members | prin),
            evidence=[
                EvidenceItem("agent_to_agent_links", "observed", 0.2,
                             {"agents": sorted(members)[:30], "relations": dict(relations)}, event_refs(evs)),
                EvidenceItem("cross_principal_agent_ring", "inferred", min(0.45, 0.08 * len(members) + 0.05 * len(prin)),
                             {"principal_count": len(prin)}),
            ],
            occurrence_count=len(evs),
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=["agentic", "counterparty"],
            competing_explanations=[
                {"id": "agent_marketplace_or_protocol", "note": "Agent marketplaces and multi-agent protocols route legitimate work between agents of different owners."},
                _VICTIM,
            ],
            novelty=1.0,
            baseline={"agents": len(members), "principals": len(prin)},
            episode_count=len(evs),
            detector=NAME,
        ))
        if clusters >= cfg.max_patterns_per_detector:
            break
    return DetectorOutput(NAME, patterns, {}, {
        "agents": len(agent_entities), "spawn_anomalies": spawned, "tool_signatures": tool_patterns,
        "interaction_clusters": clusters, "reported": len(patterns),
    })
