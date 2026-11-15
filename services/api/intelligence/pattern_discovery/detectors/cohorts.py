"""Behavioural cohorts: groups of entities whose activity is near-identical.

Each entity with enough activity becomes a sparse vector: TF-IDF over its
behavioural tokens plus a coarse time-of-day profile. Pairs are compared
through an inverted index on each entity's most distinctive tokens (no
all-pairs blow-up). The similarity threshold is *learned from the
population*: it is the larger of the configured floor and the 99th percentile
of similarity between deterministic random pairs, so a tenant whose users all
behave alike does not produce cohorts of "everyone".

Near-identical cohorts at scale are a classic signature of scripted or farmed
accounts and of agent fleets running one playbook, and they are also the
signature of synthetic monitoring and one popular onboarding flow, which is
why those explanations are always attached.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from ..contracts import KIND_BEHAVIORAL_COHORT, EvidenceItem, RawPattern
from .attributes import _UnionFind
from .base import DetectorOutput
from .frame import DiscoveryFrame, bounds, entity_kinds, event_refs, plural, risk_categories_for

NAME = "behavioral_cohorts"
MAX_ENTITIES = 3_000
MAX_COMPARE = 200
RANDOM_PAIRS = 2_000
MAX_COHORT_SHARE = 0.3
#: A token performed by more than this share of eligible entities is "normal flow".
MAX_TOKEN_SHARE = 0.3


def _vector(events, idf) -> dict[str, float]:
    tf = Counter(e.token for e in events)
    vec = {t: c * idf.get(t, 1.0) for t, c in tf.items()}
    hours = Counter(f"hour:{e.ts.hour // 4}" for e in events if e.ts)
    total = sum(hours.values()) or 1
    scale = 0.5 * (sum(v * v for v in vec.values()) ** 0.5 or 1.0)
    for h, c in hours.items():
        vec[h] = scale * c / total
    norm = sum(v * v for v in vec.values()) ** 0.5 or 1.0
    return {k: v / norm for k, v in vec.items()}


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def detect_behavioral_cohorts(frame: DiscoveryFrame) -> DetectorOutput:
    cfg = frame.config
    active = {e: evs for e, evs in frame.by_entity.items() if len(evs) >= cfg.cohort_min_events}
    if len(active) < max(cfg.min_cluster * 2, 8):
        return DetectorOutput(NAME, [], {}, {"eligible_entities": len(active), "reported": 0})
    entities = sorted(active, key=lambda e: (-len(active[e]), e))[:MAX_ENTITIES]
    df = Counter()
    for e in entities:
        df.update({ev.token for ev in active[e]})
    n = len(entities)
    idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
    vecs = {e: _vector(active[e], idf) for e in entities}

    # Population similarity reference: deterministic pseudo-random pairs.
    sims = []
    for i in range(min(RANDOM_PAIRS, n * (n - 1) // 2)):
        a = entities[(i * 7919) % n]
        b = entities[(i * 104729 + 1) % n]
        if a != b:
            sims.append(_cos(vecs[a], vecs[b]))
    sims.sort()
    p99 = sims[int(0.99 * (len(sims) - 1))] if sims else 0.0
    threshold = min(0.995, max(cfg.cohort_similarity, p99 + 0.01))

    index: dict[str, list[str]] = defaultdict(list)
    for e in entities:
        top = sorted((k for k in vecs[e] if not k.startswith("hour:")), key=lambda k: -vecs[e][k])[:3]
        for k in top:
            index[k].append(e)
    uf = _UnionFind()
    pair_sims: dict[tuple[str, str], float] = {}
    for e in entities:
        seen: set[str] = set()
        top = sorted((k for k in vecs[e] if not k.startswith("hour:")), key=lambda k: -vecs[e][k])[:3]
        for k in top:
            for other in index[k][:MAX_COMPARE]:
                if other <= e or other in seen:
                    continue
                seen.add(other)
                s = _cos(vecs[e], vecs[other])
                if s >= threshold:
                    uf.union(e, other)
                    pair_sims[(e, other)] = s

    groups: dict[str, list[str]] = defaultdict(list)
    for e in uf.parent:
        groups[uf.find(e)].append(e)
    min_size = max(cfg.min_cluster, 4)
    cohorts = sorted((sorted(g) for g in groups.values()
                      if len(g) >= min_size and len(g) <= max(min_size, MAX_COHORT_SHARE * frame.entity_count)),
                     key=lambda g: (-len(g), g))

    patterns: list[RawPattern] = []
    suppressed_normal = 0
    for members in cohorts[: cfg.max_patterns_per_detector * 2]:
        if len(patterns) >= cfg.max_patterns_per_detector:
            break
        ms = set(members)
        centroid: Counter = Counter()
        for m in members:
            for k, v in vecs[m].items():
                centroid[k] += v
        tokens = [k for k, _ in sorted(centroid.items(), key=lambda kv: (-kv[1], kv[0]))
                  if not k.startswith("hour:")][:6]
        # A cohort whose dominant behaviour is what most entities do is the
        # product's normal flow, not a pattern.
        distinctive = [t for t in tokens if df[t] <= MAX_TOKEN_SHARE * n]
        if not distinctive:
            suppressed_normal += 1
            continue
        peak = max((k for k in centroid if k.startswith("hour:")), key=lambda k: centroid[k], default=None)
        within = [s for (a, b), s in pair_sims.items() if a in ms and b in ms]
        mean_sim = sum(within) / len(within) if within else threshold
        evs = [ev for m in members for ev in active[m]]
        first, last = bounds(evs)
        signature = {"tokens": sorted(tokens), "peak_hours": peak, "size_bucket": int(math.log2(len(members)))}
        excess = (mean_sim - p99) / max(1e-6, 1 - p99)
        evidence = [
            EvidenceItem("near_identical_behavior", "observed", 0.2, {
                "members": len(members), "mean_similarity": round(mean_sim, 4), "dominant_tokens": tokens,
            }, event_refs(evs)),
            EvidenceItem("beyond_population_similarity", "inferred", max(0.05, min(0.4, 0.4 * excess)), {
                "population_p99_similarity": round(p99, 4), "threshold": round(threshold, 4),
            }),
        ]
        if peak is not None and centroid[peak] / max(sum(v for k, v in centroid.items() if k.startswith("hour:")), 1e-9) > 0.8:
            evidence.append(EvidenceItem("synchronized_schedule", "inferred", 0.1, {"peak_hour_bin": peak}))
        kinds = entity_kinds(members)
        patterns.append(RawPattern(
            kind=KIND_BEHAVIORAL_COHORT,
            signature=signature,
            title=f"Behavioural cohort of {plural(len(members), 'entity')} acting alike",
            summary=(f"{plural(len(members), 'entity')} show near-identical activity "
                     f"(mean similarity {mean_sim:.3f} vs population p99 {p99:.3f}), dominated by "
                     f"{', '.join(distinctive[:3])}."),
            affected_entities=members,
            evidence=evidence,
            occurrence_count=len(evs),
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=risk_categories_for(tokens=tokens, entity_kinds=kinds),
            competing_explanations=[
                {"id": "popular_onboarding_flow",
                 "note": "A short, guided product flow makes new users look alike."},
                {"id": "synthetic_monitoring_or_test_accounts",
                 "note": "Uptime checks, QA suites and demo accounts run identical scripts."},
                {"id": "same_agent_template",
                 "note": "Independent agents built from one template behave identically without a common operator."},
            ],
            novelty=1.0,
            baseline={"population_p99_similarity": round(p99, 4), "threshold": round(threshold, 4),
                      "mean_similarity": round(mean_sim, 4)},
            episode_count=len(evs),
            detector=NAME,
        ))
    return DetectorOutput(NAME, patterns, {}, {
        "eligible_entities": len(active), "threshold": round(threshold, 4),
        "cohorts": len(cohorts), "normal_flow_cohorts_skipped": suppressed_normal,
        "reported": len(patterns),
    })
