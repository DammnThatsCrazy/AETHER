"""Behavioural outliers grouped by *how* they are extreme.

Per entity: activity rate, token diversity, failure ratio, distinct devices /
IPs / wallets / payment instruments / emails, distinct counterparties and
moved amount. Each feature is scored with a robust z (median / MAD), upward
only. Entities that are extreme on the same *set* of features form one
pattern ("entities with extreme device churn and failure ratio"), so the
queue receives a handful of explainable shapes instead of one row per entity.

This is the deterministic, dependency-free counterpart of the IsolationForest
+ autoencoder ``AnomalyDetection`` model in ``services/ml``; both answer
"unusual against the population", this one with features a reviewer can read.
"""
from __future__ import annotations

from collections import defaultdict

from ..contracts import KIND_OUTLIER, EvidenceItem, RawPattern
from .base import DetectorOutput
from .frame import (
    DiscoveryFrame, bounds, entity_kinds, event_refs, plural, risk_categories_for, robust_stats,
)

NAME = "outliers"

#: feature -> minimum absolute value before it can count as extreme.
_FLOORS = {
    "events_per_active_hour": 30.0,
    "distinct_tokens": 15.0,
    "fail_ratio": 0.5,
    "distinct_device": 3.0,
    "distinct_ip": 4.0,
    "distinct_wallet": 4.0,
    "distinct_payment_instrument": 3.0,
    "distinct_email": 3.0,
    "distinct_counterparties": 10.0,
    "amount_total": 0.0,
}
_LABELS = {
    "events_per_active_hour": "activity rate",
    "distinct_tokens": "action diversity",
    "fail_ratio": "failure ratio",
    "distinct_device": "device churn",
    "distinct_ip": "IP churn",
    "distinct_wallet": "wallet churn",
    "distinct_payment_instrument": "payment-instrument churn",
    "distinct_email": "email churn",
    "distinct_counterparties": "counterparty fan-out",
    "amount_total": "moved amount",
}
_ATTR_FEATURES = {"device", "ip", "wallet", "payment_instrument", "email"}


def _cohort(entity: str) -> str:
    kind = entity.split(":", 1)[0]
    return {"user": "human", "entity": "human", "anon": "anonymous", "session": "anonymous"}.get(kind, kind)


def _features(events) -> dict[str, float]:
    f: dict[str, float] = {}
    hours = {(e.ts.date(), e.ts.hour) for e in events if e.ts}
    f["events_per_active_hour"] = len(events) / max(len(hours), 1)
    f["distinct_tokens"] = float(len({e.token for e in events}))
    outcomes = [e.outcome for e in events if e.outcome]
    if len(outcomes) >= 3:
        f["fail_ratio"] = outcomes.count("fail") / len(outcomes)
    vals: dict[str, set] = defaultdict(set)
    cps: set = set()
    amount = 0.0
    has_amount = False
    for e in events:
        for a in e.attributes:
            if a.type in _ATTR_FEATURES:
                vals[a.type].add(a.value)
        cps.update(c for _r, c in e.counterparties)
        if e.amount is not None:
            amount += abs(e.amount)
            has_amount = True
    for t in _ATTR_FEATURES:
        f[f"distinct_{t}"] = float(len(vals.get(t, ())))
    f["distinct_counterparties"] = float(len(cps))
    if has_amount:
        f["amount_total"] = amount
    return f


def detect_outliers(frame: DiscoveryFrame) -> DetectorOutput:
    """Robust outliers *within each cohort*: agents are compared with agents,
    people with people, anonymous traffic with anonymous traffic. A cohort
    smaller than ``outlier_min_population`` is not scored."""
    cfg = frame.config
    feats = {e: _features(evs) for e, evs in frame.by_entity.items()}
    cohorts: dict[str, list[str]] = defaultdict(list)
    for entity in feats:
        cohorts[_cohort(entity)].append(entity)
    groups: dict[tuple[str, ...], list[tuple[str, dict]]] = defaultdict(list)
    cohort_stats: dict[str, dict[str, tuple[float, float]]] = {}
    for cohort, members in cohorts.items():
        if len(members) < cfg.outlier_min_population:
            continue
        stats = {}
        names = sorted({k for m in members for k in feats[m]})
        for name in names:
            values = [feats[m][name] for m in members if name in feats[m]]
            if len(values) >= cfg.outlier_min_population and len(set(values)) > 1:
                stats[name] = robust_stats(values)
        cohort_stats[cohort] = stats
        for entity in members:
            f = feats[entity]
            extreme = {}
            for name, (med, sigma) in stats.items():
                if name not in f or f[name] < _FLOORS.get(name, 0.0):
                    continue
                z = (f[name] - med) / sigma
                if z >= cfg.outlier_z:
                    extreme[name] = round(z, 2)
            if extreme:
                groups[(cohort, *sorted(extreme))].append((entity, {n: (f[n], extreme[n]) for n in extreme}))
    if not cohort_stats:
        return DetectorOutput(NAME, [], {}, {"population": len(feats), "reported": 0})

    patterns: list[RawPattern] = []
    for key in sorted(groups, key=lambda k: (-len(groups[k]), k))[: cfg.max_patterns_per_detector]:
        cohort, features = key[0], key[1:]
        stats = cohort_stats[cohort]
        members = sorted(groups[key])
        ents = [m for m, _ in members]
        if not frame.entities_share_ok(len(ents)):
            continue
        evs = [ev for e in ents for ev in frame.by_entity[e]]
        first, last = bounds(evs)
        top_z = max(z for _m, d in members for _v, z in d.values())
        labels = [_LABELS.get(k, k) for k in features]
        attr_types = [k.replace("distinct_", "") for k in features if k.replace("distinct_", "") in _ATTR_FEATURES]
        key = features
        patterns.append(RawPattern(
            kind=KIND_OUTLIER,
            signature={"extreme_features": list(key), "cohort": cohort},
            title=f"Extreme {' + '.join(labels)} among {cohort} entities",
            summary=(f"{plural(len(ents), 'entity')} are extreme on {', '.join(labels)} "
                     f"(robust z up to {top_z:.1f} against {len(cohorts[cohort])} {cohort} entities)."),
            affected_entities=ents,
            evidence=[
                EvidenceItem("feature_extremes", "observed", 0.1, {
                    "population": len(cohorts[cohort]), "cohort": cohort,
                    "population_median": {k: round(stats[k][0], 3) for k in key},
                    "entities": [{"entity": m, "values": {n: {"value": round(v, 3), "robust_z": z} for n, (v, z) in d.items()}}
                                 for m, d in members[:20]],
                }, event_refs(evs)),
                EvidenceItem("robust_outlier", "inferred", min(0.4, 0.03 * top_z + 0.05 * (len(key) - 1)),
                             {"max_robust_z": top_z, "threshold": cfg.outlier_z, "features": list(key)}),
            ],
            occurrence_count=len(evs),
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=risk_categories_for(
                tokens=["!fail"] if "fail_ratio" in key else [], attr_types=attr_types,
                entity_kinds=entity_kinds(ents),
            ),
            competing_explanations=[
                {"id": "power_user_or_integration",
                 "note": "Heavy legitimate users, internal tools and B2B integrations sit far from the median."},
                {"id": "identity_resolution_gap",
                 "note": "Unresolved identity can fold several real people into one entity, inflating its counts."},
            ],
            novelty=1.0,
            baseline={"population": len(cohorts[cohort]), "cohort": cohort, "max_robust_z": top_z},
            episode_count=len(evs),
            detector=NAME,
        ))
    return DetectorOutput(NAME, patterns, {}, {
        "population": len(feats), "cohorts": {c: len(m) for c, m in cohorts.items()},
        "groups": len(groups), "reported": len(patterns),
    })
