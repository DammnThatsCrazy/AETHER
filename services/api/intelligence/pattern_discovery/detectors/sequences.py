"""Recurring-sequence discovery (no predefined sequences).

Each entity's activity is split into sessions and reduced to behavioural
tokens (``event_type`` plus outcome, or plus a free-text message template).
Runs of the same token collapse to ``token+`` so "fail, fail, fail, fail"
and "fail, fail" are one shape. Every contiguous n-gram (n = 3..5) is counted
with the distinct entities that performed it.

An n-gram is surprising when it occurs more often than an order-1 Markov model
of the same window predicts (its *lift*): the pairwise transitions are
ordinary, but the longer chain is not. It is *novel* when the tenant baseline
has not seen it at this rate. Patterns that most of the population performs
are the product's normal flow and are never reported.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from ..baselines import signature_novelty
from ..contracts import KIND_SEQUENCE, EvidenceItem, RawPattern, signature_hash
from .base import DetectorOutput
from .frame import DiscoveryFrame, bounds, event_refs, plural, risk_categories_for

NAME = "sequences"


def _collapse(session):
    out = []  # [(token, first_event)]
    for ev in session:
        if out and (out[-1][0] == ev.token or out[-1][0] == ev.token + "+"):
            if not out[-1][0].endswith("+"):
                out[-1] = (ev.token + "+", out[-1][1])
            continue
        out.append((ev.token, ev))
    return out


def detect_sequences(frame: DiscoveryFrame) -> DetectorOutput:
    cfg = frame.config
    sessions = [
        _collapse(s) for entity_sessions in frame.sessions().values() for s in entity_sessions
    ]
    sessions = [s for s in sessions if s]
    entity_of_session = [
        entity for entity, ss in frame.sessions().items() for s in ss if s
    ]
    uni: Counter = Counter()
    pred: Counter = Counter()
    bi: Counter = Counter()
    for s in sessions:
        toks = [t for t, _ in s]
        uni.update(toks)
        for a, b in zip(toks, toks[1:]):
            bi[(a, b)] += 1
            pred[a] += 1
    total_uni = sum(uni.values()) or 1

    grams: dict[tuple[str, ...], dict] = {}
    positions = Counter()
    for s, entity in zip(sessions, entity_of_session):
        toks = [t for t, _ in s]
        for n in range(cfg.sequence_min_n, cfg.sequence_max_n + 1):
            if len(toks) < n:
                continue
            positions[n] += len(toks) - n + 1
            for i in range(len(toks) - n + 1):
                g = tuple(toks[i:i + n])
                if len(set(t.rstrip("+") for t in g)) < 2:
                    continue
                rec = grams.setdefault(g, {"count": 0, "entities": set(), "events": [], "occ_events": []})
                rec["count"] += 1
                rec["entities"].add(entity)
                if len(rec["events"]) < 25:
                    rec["events"].append(s[i][1])
                rec["occ_events"].append(s[i][1])

    n_sessions = max(len(sessions), 1)
    ngram_rates = {
        "|".join(g): round(1000.0 * r["count"] / n_sessions, 4)
        for g, r in grams.items() if len(r["entities"]) >= 2
    }
    baseline_ngrams = frame.baseline.get("ngram_rate") or {}
    has_history = int(frame.baseline.get("runs") or 0) > 0

    scored = []
    for g, rec in grams.items():
        support = len(rec["entities"])
        if support < cfg.min_support or not frame.entities_share_ok(support):
            continue
        p = uni[g[0]] / total_uni
        for a, b in zip(g, g[1:]):
            p *= bi[(a, b)] / max(pred[a], 1)
        expected = positions[len(g)] * p
        lift = rec["count"] / expected if expected > 0 else float("inf")
        key = "|".join(g)
        rate_now = 1000.0 * rec["count"] / n_sessions
        prior = baseline_ngrams.get(key)
        if prior is None:
            ng_novelty = 1.0 if has_history else 0.5
        else:
            ratio = rate_now / max(prior, 1e-9)
            ng_novelty = max(0.0, (ratio - 1) / (ratio + 1))
        if lift < cfg.sequence_min_lift and ng_novelty < 0.6:
            continue
        fails = sum(1 for t in g if "!fail" in t)
        score = math.log2(min(lift, 1e6) + 1) * math.sqrt(support) * (1 + ng_novelty) * (1 + 0.5 * bool(fails))
        scored.append((score, g, rec, lift, expected, ng_novelty, prior))

    scored.sort(key=lambda x: (-x[0], x[1]))
    kept: list[tuple] = []
    for item in scored:
        g, rec = item[1], item[2]
        support = len(rec["entities"])
        dominated = any(
            len(k[1]) > len(g) and _contains(k[1], g) and len(k[2]["entities"]) >= 0.8 * support
            for k in kept
        )
        if dominated:
            continue
        kept = [k for k in kept if not (len(g) > len(k[1]) and _contains(g, k[1])
                                         and support >= 0.8 * len(k[2]["entities"]))]
        kept.append(item)
        if len(kept) >= cfg.max_patterns_per_detector * 2:
            break

    patterns: list[RawPattern] = []
    for score, g, rec, lift, expected, ng_novelty, prior in kept[: cfg.max_patterns_per_detector]:
        entities = sorted(rec["entities"])
        signature = {"tokens": list(g)}
        sig = signature_hash(KIND_SEQUENCE, signature)
        _sig_novelty, sig_info = signature_novelty(frame.baseline, sig, len(entities))
        novelty = round(ng_novelty, 3) if has_history else 1.0
        first, last = bounds(rec["occ_events"])
        fails = [t for t in g if "!fail" in t]
        recovered = bool(fails) and any("!ok" in t for t in g[g.index(fails[0]) + 1:])
        evidence = [
            EvidenceItem("recurring_sequence", "observed", 0.2,
                         {"tokens": list(g), "entities": len(entities), "occurrences": rec["count"]},
                         event_refs(rec["events"])),
        ]
        if math.isfinite(lift) and lift >= cfg.sequence_min_lift:
            evidence.append(EvidenceItem("sequence_lift", "inferred", min(0.45, 0.1 * math.log2(lift)),
                                         {"lift": round(lift, 2), "expected_occurrences": round(expected, 3),
                                          "model": "order1_markov_same_window"}))
        elif not math.isfinite(lift):
            evidence.append(EvidenceItem("sequence_lift", "inferred", 0.45,
                                         {"lift": None, "expected_occurrences": 0.0,
                                          "model": "order1_markov_same_window"}))
        if has_history and novelty >= 0.3:
            evidence.append(EvidenceItem("novel_sequence", "inferred", 0.3 * novelty,
                                         {"baseline_rate_per_1k_sessions": prior, **sig_info}))
        if recovered:
            evidence.append(EvidenceItem("failure_then_success", "inferred", 0.15,
                                         {"failure_tokens": sorted(set(fails))}))
        competing = [{"id": "shared_client_flow",
                      "note": "A shared app version, SDK template or integration can make many entities follow the same path."}]
        if any(t.endswith("+") and "!fail" in t for t in g):
            competing.append({"id": "client_retry_logic",
                              "note": "Automatic retries repeat failures without any intent behind them."})
        if recovered:
            competing.append({"id": "legitimate_recovery",
                              "note": "Users who fix a mistake (wrong card, typo) produce fail-then-succeed sequences."})
        chain = " → ".join(g)
        patterns.append(RawPattern(
            kind=KIND_SEQUENCE,
            signature=signature,
            title=f"Recurring sequence: {chain}",
            summary=(f"{plural(len(entities), 'entity')} performed the sequence {chain} "
                     f"{plural(rec['count'], 'time')}"
                     + (f", {round(lift, 1)}x more often than pairwise transitions predict" if math.isfinite(lift) else
                        ", which pairwise transitions never predict")
                     + "."),
            affected_entities=entities,
            evidence=evidence,
            occurrence_count=rec["count"],
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=risk_categories_for(tokens=g),
            competing_explanations=competing,
            novelty=novelty,
            baseline={"lift": round(lift, 3) if math.isfinite(lift) else None,
                      "expected_occurrences": round(expected, 4),
                      "rate_per_1k_sessions": round(1000.0 * rec["count"] / n_sessions, 3),
                      "baseline_rate_per_1k_sessions": prior},
            episode_count=rec["count"],
            detector=NAME,
        ))
    return DetectorOutput(NAME, patterns, {"ngram_rates": ngram_rates},
                          {"sessions": len(sessions), "candidate_grams": len(grams), "reported": len(patterns)})


def _contains(long: tuple, short: tuple) -> bool:
    n = len(short)
    return any(long[i:i + n] == short for i in range(len(long) - n + 1))
