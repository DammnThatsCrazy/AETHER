"""Cross-domain correlation: independent detectors converging on the same entities.

Each detector sees one facet (sequence, shared infrastructure, timing,
structure ...). When patterns of *different kinds* implicate substantially
the same set of entities, the agreement itself is the strongest evidence the
plane produces, and it is how a reviewer gets the full story in one item:

    "14 profiles share a previously unseen sequence involving device reuse,
     delegated agents, wallet transfers and repeated tool calls."

Patterns are linked when their entity sets overlap (Jaccard >= 0.4 and at
least ``min_support`` shared entities). Connected groups spanning two or more
kinds become a composite whose affected entities are those implicated by at
least two member patterns. Schema drift is excluded: it concerns sources, not
behaviour.
"""
from __future__ import annotations

from collections import defaultdict

from ..contracts import KIND_CROSS_DOMAIN, KIND_SCHEMA_DRIFT, EvidenceItem, RawPattern
from .attributes import _UnionFind
from .base import DetectorOutput
from .frame import DetectorConfig, plural

NAME = "cross_domain"
MIN_JACCARD = 0.4


def correlate(patterns: list[RawPattern], ids: list[str], config: DetectorConfig,
              confidences: list[float], current_count: int | None = None) -> DetectorOutput:
    """``ids`` / ``confidences`` are parallel to ``patterns`` (scored members).

    The first ``current_count`` patterns come from this run; the rest are
    still-active patterns persisted by earlier runs (cross-run correlation). A
    composite must include at least one current-run member, so earlier
    agreement is never re-reported on its own."""
    current_count = len(patterns) if current_count is None else current_count
    idx = [i for i, p in enumerate(patterns) if p.kind not in (KIND_SCHEMA_DRIFT, KIND_CROSS_DOMAIN)]
    sets = {i: set(patterns[i].affected_entities) for i in idx}
    uf = _UnionFind()
    links: dict[tuple[int, int], float] = {}
    for a_pos, a in enumerate(idx):
        for b in idx[a_pos + 1:]:
            if patterns[a].kind == patterns[b].kind:
                continue
            inter = sets[a] & sets[b]
            if len(inter) < config.min_support:
                continue
            j = len(inter) / len(sets[a] | sets[b])
            if j >= MIN_JACCARD:
                uf.union(str(a), str(b))
                links[(a, b)] = j
    groups: dict[str, list[int]] = defaultdict(list)
    for i in idx:
        if str(i) in uf.parent:
            groups[uf.find(str(i))].append(i)

    out: list[RawPattern] = []
    for members in sorted(groups.values(), key=lambda g: (-len(g), g)):
        kinds = sorted({patterns[i].kind for i in members})
        if len(kinds) < 2 or not any(i < current_count for i in members):
            continue
        counts: dict[str, int] = defaultdict(int)
        for i in members:
            for e in sets[i]:
                counts[e] += 1
        core = sorted(e for e, c in counts.items() if c >= 2)
        if len(core) < config.min_support:
            continue
        member_ps = [patterns[i] for i in members]
        firsts = [p.first_observed_at for p in member_ps if p.first_observed_at]
        lasts = [p.last_observed_at for p in member_ps if p.last_observed_at]
        refs = [r for p in member_ps for ev in p.evidence for r in ev.source_event_refs]
        member_sigs = sorted(p.signature_hash for p in member_ps)
        cats = sorted({c for p in member_ps for c in p.risk_categories})
        span_days = ((max(lasts) - min(firsts)).total_seconds() / 86400) if firsts and lasts else None
        facets = "; ".join(p.title for p in member_ps[:5])
        jac = [j for (a, b), j in links.items() if a in members and b in members]
        out.append(RawPattern(
            kind=KIND_CROSS_DOMAIN,
            signature={"member_signatures": member_sigs},
            title=f"{plural(len(core), 'entity')} linked across {len(kinds)} independent signals",
            summary=(f"{plural(len(core), 'entity')} appear in {plural(len(member_ps), 'pattern')} of "
                     f"{len(kinds)} different kinds ({', '.join(kinds)})"
                     + (f", spanning {span_days:.1f} days" if span_days is not None else "")
                     + f": {facets}."),
            affected_entities=core,
            evidence=[
                EvidenceItem("independent_detector_agreement", "inferred",
                             min(0.5, 0.15 * len(kinds) + 0.1 * (sum(jac) / len(jac) if jac else 0)), {
                                 "kinds": kinds,
                                 "cross_run": any(i >= current_count for i in members),
                                 "members": [{"pattern_id": ids[i], "kind": patterns[i].kind,
                                              "from_earlier_run": i >= current_count,
                                              "title": patterns[i].title, "confidence": confidences[i],
                                              "entities": len(sets[i])} for i in members],
                                 "mean_jaccard": round(sum(jac) / len(jac), 3) if jac else None,
                             }, refs),
            ],
            occurrence_count=sum(p.occurrence_count for p in member_ps),
            first_observed_at=min(firsts) if firsts else None,
            last_observed_at=max(lasts) if lasts else None,
            risk_categories=cats,
            competing_explanations=[
                {"id": "common_cause", "note": "One upstream cause (a promotion, an outage, an integration) can surface in several detectors at once."},
                {"id": "member_explanations_apply",
                 "note": "Each member pattern's own competing explanations still apply; agreement raises, but does not settle, the question."},
            ],
            novelty=max(p.novelty for p in member_ps),
            baseline={"member_count": len(member_ps)},
            episode_count=sum(p.episode_count for p in member_ps),
            detector=NAME,
            member_pattern_ids=[ids[i] for i in members],
        ))
    return DetectorOutput(NAME, out[: config.max_patterns_per_detector], {}, {
        "links": len(links), "composites": len(out),
    })
