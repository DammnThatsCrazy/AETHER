"""Tenant baselines: what is *normal* here, before anything is called anomalous.

A baseline is a decayed (EWMA) summary of previous discovery runs for one
tenant. Detectors compare the current window against it so a recurring,
well-understood pattern stops looking novel, and a sudden change does:

* ``token_rate``      – events per hour per behavioural token
* ``ngram_rate``      – per-1k-session frequency of token n-grams
* ``signatures``      – how often each pattern signature has been seen, and its
                        decayed support (drives novelty)
* ``field_profiles``  – schema presence / dominant type per event group
                        (drives schema drift)
* ``motif_rate``      – decayed counts of typed graph motifs
* ``attribute_degree``– robust degree statistics per attribute type
* ``segment_rate``    – events per hour per ``dimension=value|token`` for the
                        segment dimensions (entity kind, application,
                        geography, agent type), so a shift inside one cohort is
                        visible even when the tenant-wide rate looks normal
* ``hour_of_week``    – per-token mean events per hour for each of the 168
                        hours of the week (seasonality), with observation counts

The structure is a plain dict so it persists as one JSONB row per tenant.
Sizes are capped (least-recently-seen keys are evicted first).
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import ConflictError, utc_now

from repositories.repos import BaseRepository

ALPHA = 0.3
MAX_TOKENS = 2_000
MAX_NGRAMS = 4_000
MAX_SIGNATURES = 6_000
MAX_MOTIFS = 2_000
MAX_SEGMENT_KEYS = 6_000
MAX_SEASONAL_TOKENS = 300
HOURS_PER_WEEK = 168
MAX_GROUPS = 400
MAX_FIELDS_PER_GROUP = 300
#: A signature seen in at least this many prior runs is "familiar".
FAMILIAR_RUNS = 3


def empty_baseline(tenant_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "runs": 0,
        "token_rate": {},
        "ngram_rate": {},
        "signatures": {},
        "field_profiles": {},
        "group_events": {},
        "motif_rate": {},
        "attribute_degree": {},
        "segment_rate": {},
        "hour_of_week": {},
        "revision": 0,
        "updated_at": None,
    }


def _ewma(prev: Optional[float], value: float, runs: int) -> float:
    if prev is None or runs == 0:
        return float(value)
    return (1 - ALPHA) * float(prev) + ALPHA * float(value)


def _cap(mapping: dict[str, Any], limit: int, key=lambda kv: kv[1]) -> dict[str, Any]:
    if len(mapping) <= limit:
        return mapping
    return dict(sorted(mapping.items(), key=key, reverse=True)[:limit])


def signature_novelty(baseline: dict[str, Any], sig_hash: str, support: float) -> tuple[float, dict[str, Any]]:
    """Novelty in [0, 1] of a signature with ``support`` in this window.

    Never seen -> 1.0. Seen before at the same strength -> ~0. Growing well
    beyond its usual support -> rises toward 1 again. Familiar signatures
    (seen in many runs) are damped further: recurrence is the definition of
    normal.
    """
    seen = (baseline.get("signatures") or {}).get(sig_hash)
    if not seen:
        return 1.0, {"seen_runs": 0}
    usual = max(float(seen.get("ewma_support") or 0.0), 1e-9)
    ratio = support / usual
    growth = max(0.0, (ratio - 1.0) / (ratio + 1.0))
    runs = int(seen.get("seen_runs") or 0)
    damp = 0.5 if runs >= FAMILIAR_RUNS else 1.0
    return round(min(1.0, growth * damp), 3), {
        "seen_runs": runs, "usual_support": round(usual, 3), "support_ratio": round(ratio, 3),
    }


def token_expected_rate(baseline: dict[str, Any], token: str) -> Optional[float]:
    rate = (baseline.get("token_rate") or {}).get(token)
    return float(rate) if rate is not None else None


def segment_expected_rate(baseline: dict[str, Any], segment_key: str) -> Optional[float]:
    rate = (baseline.get("segment_rate") or {}).get(segment_key)
    return float(rate) if rate is not None else None


def seasonal_expected_rate(baseline: dict[str, Any], token: str, hour_of_week: int) -> Optional[float]:
    """Expected events/hour for ``token`` at this hour of the week, when that
    hour has been observed at least twice; otherwise None (fall back to the flat rate)."""
    entry = (baseline.get("hour_of_week") or {}).get(token)
    if not entry:
        return None
    means, counts = entry.get("mean") or [], entry.get("n") or []
    if len(means) != HOURS_PER_WEEK or len(counts) != HOURS_PER_WEEK:
        return None
    if int(counts[hour_of_week % HOURS_PER_WEEK]) < 2:
        return None
    return float(means[hour_of_week % HOURS_PER_WEEK])


def update_baseline(
    baseline: dict[str, Any],
    *,
    token_rates: dict[str, float],
    ngram_rates: dict[str, float],
    signatures: dict[str, float],
    field_profiles: dict[str, dict[str, dict[str, Any]]],
    group_events: dict[str, int],
    motif_counts: dict[str, float],
    attribute_degree: dict[str, dict[str, float]],
    segment_rates: Optional[dict[str, float]] = None,
    hour_of_week: Optional[dict[str, dict[int, float]]] = None,
) -> dict[str, Any]:
    """Fold one run's observations into the baseline (pure; returns a copy)."""
    runs = int(baseline.get("runs") or 0)
    out = dict(baseline)

    tok = dict(baseline.get("token_rate") or {})
    for key in set(tok) | set(token_rates):
        tok[key] = round(_ewma(tok.get(key), token_rates.get(key, 0.0), runs), 6)
    out["token_rate"] = _cap({k: v for k, v in tok.items() if v > 1e-6}, MAX_TOKENS)

    ng = dict(baseline.get("ngram_rate") or {})
    for key in set(ng) | set(ngram_rates):
        ng[key] = round(_ewma(ng.get(key), ngram_rates.get(key, 0.0), runs), 6)
    out["ngram_rate"] = _cap({k: v for k, v in ng.items() if v > 1e-6}, MAX_NGRAMS)

    sigs = {k: dict(v) for k, v in (baseline.get("signatures") or {}).items()}
    now = utc_now().isoformat()
    for key, support in signatures.items():
        prev = sigs.get(key)
        if prev is None:
            sigs[key] = {"seen_runs": 1, "ewma_support": float(support), "last_seen_at": now}
        else:
            prev["seen_runs"] = int(prev.get("seen_runs") or 0) + 1
            prev["ewma_support"] = round(_ewma(prev.get("ewma_support"), support, 1), 4)
            prev["last_seen_at"] = now
    out["signatures"] = _cap(sigs, MAX_SIGNATURES, key=lambda kv: str(kv[1].get("last_seen_at") or ""))

    profiles = {g: dict(p) for g, p in (baseline.get("field_profiles") or {}).items()}
    for group, fields in field_profiles.items():
        merged = dict(profiles.get(group) or {})
        for path, info in fields.items():
            prev = merged.get(path) or {}
            merged[path] = {
                "dominant_kind": info.get("dominant_kind"),
                "presence": round(_ewma(prev.get("presence"), info.get("presence", 0.0), 1 if prev else 0), 4),
                "first_seen_at": prev.get("first_seen_at") or now,
            }
        # Paths absent this run decay toward zero presence.
        for path, prev in list(merged.items()):
            if path not in fields and group in field_profiles:
                prev = dict(prev)
                prev["presence"] = round(_ewma(prev.get("presence"), 0.0, 1), 4)
                merged[path] = prev
        profiles[group] = _cap(merged, MAX_FIELDS_PER_GROUP, key=lambda kv: kv[1].get("presence", 0))
    out["field_profiles"] = dict(list(profiles.items())[:MAX_GROUPS])

    ge = dict(baseline.get("group_events") or {})
    for group, count in group_events.items():
        ge[group] = round(_ewma(ge.get(group), count, runs), 2)
    out["group_events"] = _cap(ge, MAX_GROUPS)

    mc = dict(baseline.get("motif_rate") or {})
    for key in set(mc) | set(motif_counts):
        mc[key] = round(_ewma(mc.get(key), motif_counts.get(key, 0.0), runs), 4)
    out["motif_rate"] = _cap({k: v for k, v in mc.items() if v > 1e-4}, MAX_MOTIFS)

    ad = dict(baseline.get("attribute_degree") or {})
    for attr_type, stats in attribute_degree.items():
        prev = ad.get(attr_type) or {}
        ad[attr_type] = {
            k: round(_ewma(prev.get(k), float(v), runs if prev else 0), 4) for k, v in stats.items()
        }
    out["attribute_degree"] = ad

    seg = dict(baseline.get("segment_rate") or {})
    for key in set(seg) | set(segment_rates or {}):
        seg[key] = round(_ewma(seg.get(key), (segment_rates or {}).get(key, 0.0), runs), 6)
    out["segment_rate"] = _cap({k: v for k, v in seg.items() if v > 1e-6}, MAX_SEGMENT_KEYS)

    how = {k: {"mean": list(v.get("mean") or []), "n": list(v.get("n") or [])}
           for k, v in (baseline.get("hour_of_week") or {}).items()}
    for token, hours in (hour_of_week or {}).items():
        entry = how.setdefault(token, {"mean": [0.0] * HOURS_PER_WEEK, "n": [0] * HOURS_PER_WEEK})
        if len(entry["mean"]) != HOURS_PER_WEEK:
            entry = how[token] = {"mean": [0.0] * HOURS_PER_WEEK, "n": [0] * HOURS_PER_WEEK}
        for h, rate in hours.items():
            h = int(h) % HOURS_PER_WEEK
            n = int(entry["n"][h])
            # Running mean for the first observations, then EWMA.
            entry["mean"][h] = round(rate if n == 0 else (entry["mean"][h] * n + rate) / (n + 1) if n < 4
                                     else (1 - ALPHA) * entry["mean"][h] + ALPHA * rate, 4)
            entry["n"][h] = n + 1
    out["hour_of_week"] = dict(sorted(how.items(), key=lambda kv: -sum(kv[1]["n"]))[:MAX_SEASONAL_TOKENS])

    out["runs"] = runs + 1
    out["updated_at"] = now
    return out


_MAX_WRITE_ATTEMPTS = 5


class PatternBaselineRepository(BaseRepository):
    """One baseline row per tenant, compare-and-set on ``revision``."""

    def __init__(self) -> None:
        super().__init__("pattern_discovery_baselines")

    @staticmethod
    def record_id(tenant_id: str) -> str:
        return f"{tenant_id}:pattern_baseline"

    async def get(self, tenant_id: str) -> dict[str, Any]:
        row = await self.find_by_id(self.record_id(tenant_id))
        if row and row.get("tenant_id") == tenant_id:
            return dict(row)
        return empty_baseline(tenant_id)

    async def save(self, tenant_id: str, updater) -> dict[str, Any]:
        """Apply ``updater(baseline) -> baseline`` atomically, retrying on races."""
        rid = self.record_id(tenant_id)
        for _ in range(_MAX_WRITE_ATTEMPTS):
            existing = await self.find_by_id(rid)
            current = dict(existing) if existing and existing.get("tenant_id") == tenant_id else None
            record = updater(current or empty_baseline(tenant_id))
            record["tenant_id"] = tenant_id
            if current is None:
                record["revision"] = 1
                if await self.insert_if_absent(rid, record, tenant_id):
                    return record
                continue
            record["revision"] = int(current.get("revision", 0)) + 1
            if await self.replace_if_matches(rid, record, tenant_id, {"revision": current.get("revision", 0)}):
                return record
        raise ConflictError("pattern baseline changed concurrently; retry")
