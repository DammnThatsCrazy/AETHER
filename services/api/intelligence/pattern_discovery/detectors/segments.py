"""Segment shifts: a behaviour surging inside one cohort, region, app or agent type.

A tenant-wide rate can look normal while one segment changes completely
(card declines up 12x in one country, a tool-call failure confined to one
agent framework, a signup surge from one application). For every
``dimension=value|token`` this compares the window's count with the
segment's baseline rate (Poisson tail) and reports the segment only when its
lift clearly exceeds the lift of the rest of the tenant — so a global spike
is left to the burst detector and only *localized* change is reported here.
A dimension with a single observed value (every actor is a user, say) is the
whole tenant and is never reported.

Dimensions come from extraction: ``entity_kind`` (human / agent / anonymous
cohort), ``application``, ``geography`` and ``agent_type``. Requires history.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from ..baselines import segment_expected_rate, token_expected_rate
from ..contracts import KIND_SEGMENT_SHIFT, EvidenceItem, RawPattern
from .base import DetectorOutput
from .frame import (
    DiscoveryFrame, bounds, entity_kinds, event_refs, plural, poisson_sf, risk_categories_for,
)

NAME = "segments"
MIN_EVENTS = 10
MIN_LIFT = 3.0
LOCALIZATION = 2.0


def detect_segment_shifts(frame: DiscoveryFrame) -> DetectorOutput:
    cfg = frame.config
    if int(frame.baseline.get("runs") or 0) == 0 or not frame.events:
        return DetectorOutput(NAME, [], {}, {"reported": 0, "note": "requires a baseline"})
    hours = frame.window_hours
    counts: Counter = Counter()
    events: dict[str, list] = defaultdict(list)
    token_counts = Counter(e.token for e in frame.events)
    for e in frame.events:
        for dim, val in e.segments.items():
            key = f"{dim}={val}|{e.token}"
            counts[key] += 1
            if len(events[key]) < 500:
                events[key].append(e)

    dim_values: dict[str, set[str]] = defaultdict(set)
    for e in frame.events:
        for d, v in e.segments.items():
            dim_values[d].add(v)
    for key in frame.baseline.get("segment_rate") or {}:
        d, _, rest = key.partition("=")
        dim_values[d].add(rest.split("|", 1)[0])

    candidates = []
    for key, k in counts.items():
        if k < MIN_EVENTS:
            continue
        seg, _, token = key.partition("|")
        prior = segment_expected_rate(frame.baseline, key)
        lam = (prior or 0.0) * hours
        if lam <= 0:
            # Segment never did this before: only meaningful when the segment itself is known.
            dim_val = seg + "|"
            if not any(s.startswith(dim_val) for s in (frame.baseline.get("segment_rate") or {})):
                continue
            lam = 0.5
        lift = k / lam
        p = poisson_sf(k, lam)
        if lift < MIN_LIFT or p > cfg.burst_max_p:
            continue
        dim = seg.split("=", 1)[0]
        if len(dim_values.get(dim, ())) < 2:
            continue  # the "segment" is the whole tenant: nothing to localize against
        global_prior = token_expected_rate(frame.baseline, token)
        rest_count = token_counts[token] - k
        rest_expected = (global_prior * hours - (prior or 0.0) * hours) if global_prior else 0.0
        if rest_expected > 0:
            rest_lift = rest_count / rest_expected
        else:
            rest_lift = 0.0 if rest_count == 0 else float("inf")
        if lift < LOCALIZATION * rest_lift:
            continue
        global_lift = (token_counts[token] / (global_prior * hours)) if global_prior else float("inf")
        candidates.append((lift * math.log10(1 / max(p, 1e-300)), key, seg, token, k, lam, lift, p, global_lift))

    candidates.sort(key=lambda c: (-c[0], c[1]))
    patterns: list[RawPattern] = []
    for _score, key, seg, token, k, lam, lift, p, global_lift in candidates[: cfg.max_patterns_per_detector]:
        evs = events[key]
        ents = sorted({e.entity for e in evs})
        if len(ents) < 2:
            continue
        dim, _, val = seg.partition("=")
        first, last = bounds(evs)
        glift = round(global_lift, 2) if math.isfinite(global_lift) else None
        patterns.append(RawPattern(
            kind=KIND_SEGMENT_SHIFT,
            signature={"segment": seg, "token": token},
            title=f"{token} surging in {dim.replace('_', ' ')} {val}",
            summary=(f"{token} ran at {lift:.1f}x its usual rate within {dim.replace('_', ' ')} {val} "
                     f"({k} events vs {lam:.1f} expected) while the tenant-wide lift was "
                     f"{'n/a' if glift is None else f'{glift}x'}; {plural(len(ents), 'entity')} involved."),
            affected_entities=ents,
            evidence=[
                EvidenceItem("segment_events", "observed", 0.15,
                             {"segment": seg, "token": token, "events": k}, event_refs(evs)),
                EvidenceItem("localized_rate_shift", "inferred", min(0.45, 0.08 * math.log2(lift)), {
                    "expected_events": round(lam, 3), "lift": round(lift, 2), "poisson_tail_p": p,
                    "tenant_wide_lift": glift, "localization_factor": LOCALIZATION,
                }),
            ],
            occurrence_count=k,
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=sorted(set(risk_categories_for(tokens=[token], entity_kinds=entity_kinds(ents)))
                                   | ({"geographic"} if dim == "geography" else set())
                                   | ({"agentic"} if dim == "agent_type" else set())),
            competing_explanations=[
                {"id": "segment_launch_or_campaign", "note": "A regional launch, app release or targeted campaign moves one segment."},
                {"id": "segment_definition_change", "note": "A client that starts or stops sending a segment field moves traffic between segments."},
            ],
            novelty=1.0,
            baseline={"expected_events": round(lam, 3), "lift": round(lift, 3), "tenant_wide_lift": glift},
            episode_count=k,
            detector=NAME,
        ))
    return DetectorOutput(NAME, patterns, {}, {"segment_keys": len(counts), "reported": len(patterns)})
