"""Confidence, novelty, severity and the funnel status, calibrated by analysts.

* **Confidence** is a noisy-OR of the evidence strengths, multiplied by the
  detector's *calibration factor* and clipped at the kind's cap
  (:data:`contracts.CONFIDENCE_CAPS`). Nothing a detector does can exceed its
  cap; only a human verdict leaves the funnel.
* **Calibration** comes from reviewer verdicts on earlier patterns of the same
  kind: ``factor = 0.5 + (useful + 1) / (useful + noise + 2)``, i.e. a Beta(1,1)
  prior on the kind's precision mapped into [0.5, 1.5]. Valid / malicious are
  useful, benign / duplicate are noise, unresolved is neutral.
* **Suppression** works at the *family* level (kind + the coarse shape of the
  signature): a family reviewers have dismissed three times without ever
  confirming stays in the candidate state at low priority instead of
  re-entering the queue every run.
* **Novelty** is the minimum of the detector's own novelty and the signature's
  novelty against the tenant baseline; on a tenant's first run it is capped at
  0.5 because "new" means nothing without history.
* **Severity** is for queue ordering, never for enforcement.
"""
from __future__ import annotations

import math
from typing import Any

from .baselines import signature_novelty
from .contracts import (
    CONFIDENCE_CAPS, KIND_BEHAVIORAL_COHORT, KIND_CROSS_DOMAIN, KIND_LOCKSTEP, KIND_NOVEL_MOTIF,
    KIND_OUTLIER, KIND_SCHEMA_DRIFT, KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE, KIND_TEMPORAL_BURST,
    NEEDS_REVIEW_CONFIDENCE, NEEDS_REVIEW_NOVELTY, NOISE_VERDICTS, STATUS_CANDIDATE,
    STATUS_NEEDS_REVIEW, USEFUL_VERDICTS, RawPattern, content_hash,
)

SUPPRESS_AFTER_NOISE = 3
_HIGH_WEIGHT = {"payment", "transaction", "economic", "agentic", "authentication", "identity", "security"}


def family_key(raw: RawPattern) -> str:
    s = raw.signature
    if raw.kind == KIND_SEQUENCE:
        shape = sorted({t.rstrip("+") for t in s.get("tokens", [])})
    elif raw.kind == KIND_SHARED_ATTRIBUTE:
        shape = sorted({a.split("=", 1)[0] for a in s.get("shared_attributes", [])})
    elif raw.kind == KIND_BEHAVIORAL_COHORT:
        shape = sorted(s.get("tokens", []))[:3]
    elif raw.kind in (KIND_TEMPORAL_BURST, KIND_LOCKSTEP):
        shape = [s.get("token")]
    elif raw.kind == KIND_OUTLIER:
        shape = s.get("extreme_features", [])
    elif raw.kind == KIND_NOVEL_MOTIF:
        shape = s.get("edges", [])
    elif raw.kind == KIND_SCHEMA_DRIFT:
        shape = [s.get("group")]
    elif raw.kind == KIND_CROSS_DOMAIN:
        shape = [len(s.get("member_signatures", []))]
    else:
        shape = s
    return f"{raw.kind}:{content_hash(shape, 16)}"


def calibration_factors(feedback: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-kind calibration from aggregated verdict counts.

    ``feedback`` is ``{"kinds": {kind: {verdict: n}}, "families": {family: {verdict: n}}}``.
    """
    out: dict[str, dict[str, Any]] = {}
    for kind, counts in (feedback.get("kinds") or {}).items():
        useful = sum(int(counts.get(v, 0)) for v in USEFUL_VERDICTS)
        noise = sum(int(counts.get(v, 0)) for v in NOISE_VERDICTS)
        precision = (useful + 1) / (useful + noise + 2)
        out[kind] = {"factor": round(0.5 + precision, 4), "precision_estimate": round(precision, 4),
                     "useful": useful, "noise": noise}
    return out


def suppressed_families(feedback: dict[str, Any]) -> set[str]:
    out = set()
    for family, counts in (feedback.get("families") or {}).items():
        useful = sum(int(counts.get(v, 0)) for v in USEFUL_VERDICTS)
        noise = sum(int(counts.get(v, 0)) for v in NOISE_VERDICTS)
        if noise >= SUPPRESS_AFTER_NOISE and useful == 0:
            out.add(family)
    return out


def combine(strengths: list[float]) -> float:
    remaining = 1.0
    for s in strengths:
        remaining *= 1.0 - min(max(s, 0.0), 0.99)
    return 1.0 - remaining


def severity(confidence: float, novelty: float, entities: int, categories: list[str]) -> tuple[str, float]:
    weight = 1.0 if set(categories) & _HIGH_WEIGHT else 0.7
    size = min(1.0, math.log10(entities + 1) / 2)
    score = confidence * (0.5 + 0.5 * novelty) * (0.4 + 0.6 * size) * weight
    if score >= 0.4:
        label = "critical"
    elif score >= 0.25:
        label = "high"
    elif score >= 0.12:
        label = "medium"
    else:
        label = "low"
    return label, round(score, 4)


def score(raw: RawPattern, *, baseline: dict[str, Any], calibration: dict[str, dict[str, Any]],
          suppressed: set[str]) -> dict[str, Any]:
    cap = CONFIDENCE_CAPS.get(raw.kind, 0.6)
    raw_conf = combine([e.strength for e in raw.evidence])
    cal = calibration.get(raw.kind) or {"factor": 1.0, "precision_estimate": None, "useful": 0, "noise": 0}
    confidence = round(min(cap, raw_conf * float(cal["factor"])), 3)
    has_history = int(baseline.get("runs") or 0) > 0
    sig_nov, sig_info = signature_novelty(baseline, raw.signature_hash, float(len(raw.affected_entities)))
    novelty = min(raw.novelty, sig_nov) if has_history else min(raw.novelty, 0.5)
    novelty = round(novelty, 3)
    fam = family_key(raw)
    is_suppressed = fam in suppressed
    sev, sev_score = severity(confidence, novelty, len(raw.affected_entities), raw.risk_categories)
    review = (confidence >= NEEDS_REVIEW_CONFIDENCE and novelty >= NEEDS_REVIEW_NOVELTY
              and not is_suppressed)
    status = STATUS_NEEDS_REVIEW if review else STATUS_CANDIDATE
    if is_suppressed:
        priority = "low"
    elif review and sev in ("high", "critical"):
        priority = "high"
    elif review:
        priority = "normal"
    else:
        priority = "low"
    return {
        "confidence": confidence,
        "confidence_cap": cap,
        "raw_confidence": round(raw_conf, 3),
        "calibration": cal,
        "novelty": novelty,
        "novelty_detail": {"detector": round(raw.novelty, 3), "signature": sig_nov, **sig_info,
                           "history": has_history},
        "severity": sev,
        "severity_score": sev_score,
        "family": fam,
        "suppressed_by_feedback": is_suppressed,
        "status": status,
        "priority": priority,
    }
