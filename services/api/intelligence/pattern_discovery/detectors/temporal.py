"""Temporal anomalies: bursts against the tenant's normal rate, and lockstep.

**Bursts.** Each behavioural token's events are bucketed (default 5 minutes).
The expected rate comes from the tenant baseline when it exists, otherwise
from the same window with the busiest bucket left out (so the burst does not
set its own bar). A bucket is a burst when its count is both large in absolute
terms and improbable under a Poisson model of the expected rate. Adjacent
burst buckets merge.

**Lockstep.** Many distinct entities performing the same token inside one
short window (default 60 s), repeatedly, with largely the same membership.
Coordinated action is far stronger evidence than a busy minute; a single
lockstep minute is reported with lower strength.
"""
from __future__ import annotations

import math
from collections import defaultdict

from ..baselines import token_expected_rate
from ..contracts import KIND_LOCKSTEP, KIND_TEMPORAL_BURST, EvidenceItem, RawPattern
from .base import DetectorOutput
from .frame import (
    DiscoveryFrame, bounds, entity_kinds, event_refs, plural, poisson_sf, risk_categories_for,
)

NAME = "temporal"
LOCKSTEP_JACCARD = 0.6


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def detect_temporal(frame: DiscoveryFrame) -> DetectorOutput:
    cfg = frame.config
    if frame.window_start is None:
        return DetectorOutput(NAME, [], {}, {"reported": 0})
    origin = frame.window_start.timestamp()
    width = cfg.burst_window_seconds
    n_buckets = max(1, int((frame.window_end.timestamp() - origin) // width) + 1)
    by_token: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for ev in frame.events:
        if ev.ts:
            by_token[ev.token][int((ev.ts.timestamp() - origin) // width)].append(ev)

    patterns: list[RawPattern] = []
    bursts_found = 0
    for token in sorted(by_token):
        buckets = by_token[token]
        counts = {b: len(v) for b, v in buckets.items()}
        total = sum(counts.values())
        prior_rate = token_expected_rate(frame.baseline, token)
        if prior_rate is not None and prior_rate > 0:
            lam = prior_rate * width / 3600.0
            source = "tenant_baseline"
        else:
            top = max(counts.values())
            lam = (total - top) / max(n_buckets - 1, 1) if n_buckets > 1 else 0.0
            lam = max(lam, 0.5)
            source = "same_window_excluding_peak"
        flagged = sorted(
            b for b, k in counts.items()
            if k >= cfg.burst_min_events and k >= 3 * lam and poisson_sf(k, lam) <= cfg.burst_max_p
        )
        if not flagged:
            continue
        runs: list[list[int]] = [[flagged[0]]]
        for b in flagged[1:]:
            if b == runs[-1][-1] + 1:
                runs[-1].append(b)
            else:
                runs.append([b])
        evs = [ev for b in flagged for ev in buckets[b]]
        ents = sorted({ev.entity for ev in evs})
        if len(ents) < 2:
            continue
        bursts_found += len(runs)
        peak = max(flagged, key=lambda b: counts[b])
        p = poisson_sf(counts[peak], lam)
        first, last = bounds(evs)
        strength = min(0.45, 0.04 * -math.log10(max(p, 1e-300)))
        patterns.append(RawPattern(
            kind=KIND_TEMPORAL_BURST,
            signature={"token": token},
            title=f"Burst of {token}",
            summary=(f"{plural(len(evs), 'event')} of {token} from {plural(len(ents), 'entity')} in "
                     f"{plural(len(runs), 'burst')}; peak {counts[peak]} per {width // 60} min vs "
                     f"{lam:.2f} expected."),
            affected_entities=ents,
            evidence=[
                EvidenceItem("event_burst", "observed", 0.15, {
                    "bursts": [{"start_bucket": r[0], "buckets": len(r), "events": sum(counts[b] for b in r)} for r in runs[:10]],
                    "bucket_seconds": width,
                }, event_refs(evs)),
                EvidenceItem("improbable_rate", "inferred", strength, {
                    "peak_count": counts[peak], "expected_per_bucket": round(lam, 4),
                    "poisson_tail_p": p, "expected_rate_source": source,
                }),
            ],
            occurrence_count=len(evs),
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=sorted(set(risk_categories_for(tokens=[token])) | {"temporal"}),
            competing_explanations=[
                {"id": "campaign_or_launch", "note": "Marketing sends, launches and drops create legitimate spikes."},
                {"id": "backfill_or_replay", "note": "Ingestion replays and batch imports compress old activity into minutes."},
            ],
            novelty=1.0 if prior_rate is None else min(1.0, max(0.0, 1 - lam / max(counts[peak], 1))),
            baseline={"expected_per_bucket": round(lam, 4), "peak": counts[peak], "source": source},
            episode_count=len(runs),
            detector=NAME,
        ))

    # Lockstep
    lw = cfg.lockstep_window_seconds
    lock_windows: dict[str, list[tuple[int, set, list]]] = defaultdict(list)
    per_token_minutes: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for ev in frame.events:
        if ev.ts:
            per_token_minutes[ev.token][int((ev.ts.timestamp() - origin) // lw)].append(ev)
    for token, minutes in per_token_minutes.items():
        for m, evs in sorted(minutes.items()):
            ents = {ev.entity for ev in evs}
            if len(ents) >= cfg.lockstep_min_entities:
                lock_windows[token].append((m, ents, evs))
    lock_found = 0
    for token in sorted(lock_windows):
        groups: list[dict] = []
        for m, ents, evs in lock_windows[token]:
            for g in groups:
                if _jaccard(g["core"], ents) >= LOCKSTEP_JACCARD:
                    g["windows"].append((m, ents, evs))
                    g["core"] = g["core"] | ents
                    break
            else:
                groups.append({"core": set(ents), "windows": [(m, ents, evs)]})
        for g in groups:
            windows = g["windows"]
            repeated = len(windows) >= 2
            if not repeated and len(g["core"]) < 2 * cfg.lockstep_min_entities:
                continue
            appear: dict[str, int] = defaultdict(int)
            for _m, ents, _e in windows:
                for e in ents:
                    appear[e] += 1
            members = sorted(e for e, c in appear.items() if c >= max(1, len(windows) // 2))
            if len(members) < cfg.lockstep_min_entities or not frame.entities_share_ok(len(members)):
                continue
            lock_found += 1
            evs = [ev for _m, _ents, es in windows for ev in es if ev.entity in set(members)]
            first, last = bounds(evs)
            patterns.append(RawPattern(
                kind=KIND_LOCKSTEP,
                signature={"token": token, "size_bucket": int(math.log2(len(members))),
                           "repeated": repeated},
                title=f"Lockstep {token} by {plural(len(members), 'entity')}",
                summary=(f"{plural(len(members), 'entity')} performed {token} within the same "
                         f"{lw}-second window {plural(len(windows), 'time')}."),
                affected_entities=members,
                evidence=[
                    EvidenceItem("synchronized_action", "observed", 0.2, {
                        "windows": [{"window": m, "entities": len(ents)} for m, ents, _ in windows[:20]],
                        "window_seconds": lw,
                    }, event_refs(evs)),
                    EvidenceItem("repeated_coordination" if repeated else "single_coordination", "inferred",
                                 min(0.5, 0.15 * len(windows)) if repeated else 0.15,
                                 {"windows": len(windows), "membership_jaccard_min": LOCKSTEP_JACCARD}),
                ],
                occurrence_count=len(evs),
                first_observed_at=first,
                last_observed_at=last,
                risk_categories=sorted(set(risk_categories_for(tokens=[token], entity_kinds=entity_kinds(members))) | {"temporal"}),
                competing_explanations=[
                    {"id": "scheduled_jobs", "note": "Cron-driven clients and push notifications make many entities act on the same minute."},
                    {"id": "shared_trigger_event", "note": "A broadcast (email, notification, market move) prompts simultaneous reactions."},
                ],
                novelty=1.0,
                baseline={"window_seconds": lw, "windows": len(windows)},
                episode_count=len(windows),
                detector=NAME,
            ))
    patterns.sort(key=lambda p: (-len(p.affected_entities), p.title))
    return DetectorOutput(NAME, patterns[: cfg.max_patterns_per_detector], {}, {
        "tokens": len(by_token), "bursts": bursts_found, "lockstep_groups": lock_found,
        "reported": min(len(patterns), cfg.max_patterns_per_detector),
    })
