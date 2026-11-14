"""Shared-attribute convergence clusters (devices, IPs, wallets, cards, learned fields).

Builds the bipartite graph *entity — attribute* from every linkage attribute
extraction produced, including ``field:<path>`` identifiers learned
schema-on-read. Then:

1. **Hub attributes**: per attribute type, the distribution of "how many
   entities share one value" is summarised robustly (median / MAD). A value
   shared by far more entities than its type usually is, is a hub.
   Ubiquitous values (shared by most of the population, e.g. a corporate NAT or
   a public API host) are excluded and reported as a competing explanation.
2. **Convergence clusters**: entities are linked when they share a hub, or at
   least two distinct attribute values. Connected components with
   ``min_cluster`` or more entities become one candidate each.

A cluster is evidence of *possible* common control or identity overlap. It
never merges identities: the competing explanations (shared household,
shared office network, shared custodial wallet) are always attached.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from ..contracts import KIND_SHARED_ATTRIBUTE, EvidenceItem, RawPattern
from .base import DetectorOutput
from .frame import (
    DiscoveryFrame, bounds, entity_kinds, event_refs, plural, risk_categories_for, robust_stats,
)

NAME = "shared_attributes"
HUB_SIGMA = 4.0
MAX_CLUSTER_ATTRS_IN_SIGNATURE = 5


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _type_label(attr_type: str) -> str:
    return attr_type.replace("field:", "field ").replace("_", " ")


def detect_shared_attributes(frame: DiscoveryFrame) -> DetectorOutput:
    cfg = frame.config
    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    events_by_attr: dict[tuple[str, str], list] = defaultdict(list)
    confidence: dict[tuple[str, str], float] = {}
    for ev in frame.events:
        for a in ev.attributes:
            key = (a.type, a.value)
            owners[key].add(ev.entity)
            if len(events_by_attr[key]) < 50:
                events_by_attr[key].append(ev)
            confidence[key] = max(confidence.get(key, 0.0), a.confidence)

    degrees_by_type: dict[str, list[float]] = defaultdict(list)
    for (t, _v), ents in owners.items():
        degrees_by_type[t].append(float(len(ents)))
    stats = {t: robust_stats(vals) for t, vals in degrees_by_type.items()}
    baseline_deg = frame.baseline.get("attribute_degree") or {}

    population = max(frame.entity_count, 1)
    ubiquitous: dict[tuple[str, str], int] = {}
    hubs: dict[tuple[str, str], float] = {}
    for key, ents in owners.items():
        d = len(ents)
        if d < 2:
            continue
        if d > cfg.max_entity_share * population and d > cfg.min_cluster:
            ubiquitous[key] = d
            continue
        med, sigma = stats[key[0]]
        prior = baseline_deg.get(key[0]) or {}
        if prior.get("median") is not None:
            med = max(med, float(prior["median"]))
            sigma = max(sigma, float(prior.get("sigma") or 0.0), 1.0)
        z = (d - med) / sigma
        if d >= cfg.min_cluster and z >= HUB_SIGMA:
            hubs[key] = round(z, 2)

    uf = _UnionFind()
    pair_links: Counter = Counter()
    usable = {k: e for k, e in owners.items() if 2 <= len(e) and k not in ubiquitous}
    for key, ents in usable.items():
        ordered = sorted(ents)
        if key in hubs:
            for other in ordered[1:]:
                uf.union(ordered[0], other)
        elif len(ordered) <= 50:
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    pair_links[(a, b)] += 1
    for (a, b), shared in pair_links.items():
        if shared >= 2:
            uf.union(a, b)

    members: dict[str, set[str]] = defaultdict(set)
    for key, ents in usable.items():
        for e in ents:
            if e in uf.parent:
                members[uf.find(e)].add(e)

    patterns: list[RawPattern] = []
    clusters = sorted((sorted(m) for m in members.values() if len(m) >= cfg.min_cluster),
                      key=lambda m: (-len(m), m))
    for ents in clusters[: cfg.max_patterns_per_detector]:
        es = set(ents)
        shared = sorted(
            ((k, len(owners[k] & es)) for k in usable if len(owners[k] & es) >= 2),
            key=lambda kv: (-kv[1], kv[0]),
        )
        if not shared:
            continue
        types = sorted({k[0] for k, _ in shared})
        hub_keys = [k for k, _ in shared if k in hubs]
        sig_attrs = [f"{k[0]}={k[1]}" for k, _ in (
            [(h, 0) for h in hub_keys] + [s for s in shared if s[0] not in hubs]
        )][:MAX_CLUSTER_ATTRS_IN_SIGNATURE]
        signature = {"shared_attributes": sorted(sig_attrs)}
        cluster_events = [ev for k, _ in shared for ev in events_by_attr[k] if ev.entity in es]
        first, last = bounds(cluster_events)
        n_links = sum(c for _k, c in shared)
        density = round(n_links / max(len(ents), 1), 2)
        evidence = [
            EvidenceItem("shared_attribute_values", "observed", 0.2, {
                "attributes": [
                    {"type": k[0], "value": k[1], "entities_in_cluster": c, "entities_total": len(owners[k]),
                     "extraction_confidence": confidence.get(k)}
                    for k, c in shared[:20]
                ],
            }, event_refs(cluster_events)),
        ]
        if hub_keys:
            evidence.append(EvidenceItem("attribute_hub", "inferred", min(0.45, 0.05 * max(hubs[k] for k in hub_keys)), {
                "hubs": [{"type": k[0], "value": k[1], "robust_z": hubs[k], "degree": len(owners[k])} for k in hub_keys[:10]],
            }))
        if len(types) >= 2:
            evidence.append(EvidenceItem("multi_type_convergence", "inferred", min(0.4, 0.12 * len(types)),
                                         {"attribute_types": types}))
        kinds = entity_kinds(ents)
        user_like = [e for e in ents if e.split(":", 1)[0] in ("user", "entity", "anon")]
        if len(user_like) >= 2 and ({"payment_instrument", "device"} & set(types) or "email" in types):
            evidence.append(EvidenceItem("identity_overlap_candidate", "inferred", 0.15, {
                "note": "Distinct identities share strong identifiers; review before any merge.",
                "identities": len(user_like),
            }))
        competing = []
        if {"ip", "host"} & set(types) and len(types) == len({"ip", "host"} & set(types)):
            competing.append({"id": "shared_network_infrastructure",
                              "note": "Office NAT, mobile carrier CGNAT, VPN exits and hosting providers put unrelated users behind one address."})
        if "device" in types:
            competing.append({"id": "shared_household_device",
                              "note": "Families and shared kiosks legitimately put several accounts on one device."})
        if "wallet" in types:
            competing.append({"id": "custodial_or_exchange_wallet",
                              "note": "Exchange hot wallets and custodians are counterparties to many unrelated users."})
        if any(t.startswith("field:") for t in types):
            competing.append({"id": "learned_field_semantics_unknown",
                              "note": "A learned identifier field's meaning was inferred from its shape; it may be a category, not an identity."})
        if ubiquitous:
            competing.append({"id": "excluded_ubiquitous_values",
                              "note": f"{plural(len(ubiquitous), 'value')} shared by most of the population were ignored as infrastructure."})
        competing.append({"id": "no_identity_merge",
                          "note": "Shared attributes indicate possible common control; they never establish that identities are the same."})
        type_text = ", ".join(_type_label(t) for t in types)
        patterns.append(RawPattern(
            kind=KIND_SHARED_ATTRIBUTE,
            signature=signature,
            title=f"{plural(len(ents), 'entity')} converge on shared {type_text}",
            summary=(f"{plural(len(ents), 'entity')} ({', '.join(kinds)}) share "
                     f"{plural(len(shared), 'attribute value')} across {type_text}"
                     + (f"; {plural(len(hub_keys), 'value')} are unusually widely shared" if hub_keys else "")
                     + "."),
            affected_entities=ents,
            evidence=evidence,
            occurrence_count=len(cluster_events),
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=risk_categories_for(attr_types=types, entity_kinds=kinds),
            competing_explanations=competing,
            novelty=1.0,
            baseline={"density": density, "attribute_types": types,
                      "type_degree_median": {t: round(stats[t][0], 2) for t in types if t in stats}},
            episode_count=len({ev.event_id for ev in cluster_events}),
            detector=NAME,
        ))
    degree_baseline = {t: {"median": round(m, 3), "sigma": round(s, 3)} for t, (m, s) in stats.items()}
    return DetectorOutput(NAME, patterns, {"attribute_degree": degree_baseline}, {
        "attribute_values": len(owners), "hubs": len(hubs), "ubiquitous": len(ubiquitous),
        "clusters": len(clusters), "reported": len(patterns),
    })
