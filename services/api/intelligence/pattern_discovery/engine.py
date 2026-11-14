"""Pure discovery engine: evidence in, scored pattern records + baseline delta out.

No I/O happens here. :mod:`service` loads evidence, baseline and feedback,
calls :func:`run_discovery`, and persists what comes back. Keeping the engine
pure makes every run reproducible from its inputs and testable without a
store.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from shared.logger.logger import get_logger

from .baselines import update_baseline
from .contracts import DETECTOR_VERSION, KIND_CROSS_DOMAIN, PATTERN_KINDS, RawPattern, content_hash
from .detectors import DETECTORS, DetectorConfig, DiscoveryFrame, correlate, known_motif_signatures
from .detectors.schema_drift import current_profiles
from .extraction import extract_events
from .registry import build_record
from .scoring import calibration_factors, score, suppressed_families

logger = get_logger("aether.pattern_discovery.engine")


@dataclass
class EngineResult:
    run_id: str
    tenant_id: str
    records: list[dict[str, Any]]
    detectors_run: list[str]
    kinds_run: list[str]
    stats: dict[str, Any]
    baseline_delta: dict[str, Any]
    schema: dict[str, Any] = field(default_factory=dict)
    observations_sample: list[dict[str, Any]] = field(default_factory=list)

    def apply_to_baseline(self, baseline: dict[str, Any]) -> dict[str, Any]:
        return update_baseline(baseline, **self.baseline_delta)


def new_run_id(tenant_id: str, salt: Any = None) -> str:
    return f"{tenant_id}:pdrun:{content_hash([tenant_id, salt if salt is not None else time.time_ns()], 20)}"


def run_discovery(
    tenant_id: str,
    rows: Iterable[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    feedback: Optional[dict[str, Any]] = None,
    edges: Optional[list[dict[str, Any]]] = None,
    config: Optional[DetectorConfig] = None,
    kinds: Optional[Iterable[str]] = None,
    run_id: Optional[str] = None,
) -> EngineResult:
    started = time.perf_counter()
    cfg = config or DetectorConfig()
    run_id = run_id or new_run_id(tenant_id)
    wanted = set(kinds) if kinds else set(PATTERN_KINDS)
    unknown = wanted - set(PATTERN_KINDS)
    if unknown:
        raise ValueError(f"unknown pattern kinds: {sorted(unknown)}")

    extraction = extract_events(rows, tenant_id)
    frame = DiscoveryFrame(
        tenant_id=tenant_id, extraction=extraction, baseline=baseline, config=cfg,
        external_edges=list(edges or []), known_motif_signatures=known_motif_signatures(),
    )
    feedback = feedback or {}
    calibration = calibration_factors(feedback)
    suppressed = suppressed_families(feedback)

    raws: list[RawPattern] = []
    detector_stats: dict[str, Any] = {}
    contributions: dict[str, Any] = {}
    detectors_run: list[str] = []
    kinds_run: set[str] = set()
    for name, (fn, emits) in DETECTORS.items():
        if not emits & wanted:
            continue
        t0 = time.perf_counter()
        try:
            out = fn(frame)
        except Exception as exc:  # noqa: BLE001 - one detector failing must not sink the run
            logger.warning("pattern_discovery.detector_failed",
                           extra={"tenant_id": tenant_id, "detector": name, "error_type": type(exc).__name__})
            detector_stats[name] = {"error": type(exc).__name__}
            continue
        detectors_run.append(name)
        kinds_run |= emits & wanted
        raws.extend(p for p in out.patterns if p.kind in wanted)
        contributions.update(out.baseline)
        detector_stats[name] = {**out.stats, "ms": round((time.perf_counter() - t0) * 1000, 1)}

    records: list[dict[str, Any]] = []
    for raw in raws:
        scored = score(raw, baseline=baseline, calibration=calibration, suppressed=suppressed)
        records.append(build_record(tenant_id, raw, scored, run_id=run_id))

    if KIND_CROSS_DOMAIN in wanted and len(raws) >= 2:
        cross = correlate(raws, [r["pattern_id"] for r in records], cfg, [r["confidence"] for r in records])
        detector_stats["cross_domain"] = cross.stats
        detectors_run.append("cross_domain")
        kinds_run.add(KIND_CROSS_DOMAIN)
        for raw in cross.patterns:
            scored = score(raw, baseline=baseline, calibration=calibration, suppressed=suppressed)
            records.append(build_record(tenant_id, raw, scored, run_id=run_id))

    if "field_profiles" not in contributions:
        profiles, counts = current_profiles(frame)
        contributions["field_profiles"] = {
            g: {p: {"dominant_kind": i["dominant_kind"], "presence": i["presence"]} for p, i in paths.items()}
            for g, paths in profiles.items()
        }
        contributions["group_events"] = counts
    baseline_delta = {
        "token_rates": frame.token_rates(),
        "ngram_rates": contributions.get("ngram_rates", {}),
        "signatures": {r["signature_hash"]: float(r["affected_entity_count"]) for r in records},
        "field_profiles": contributions.get("field_profiles", {}),
        "group_events": contributions.get("group_events", {}),
        "motif_counts": contributions.get("motif_counts", {}),
        "attribute_degree": contributions.get("attribute_degree", {}),
    }
    by_status: dict[str, int] = {}
    for r in records:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    stats = {
        "detector_version": DETECTOR_VERSION,
        "extraction": extraction.stats,
        "entities": frame.entity_count,
        "window_start": frame.window_start.isoformat() if frame.window_start else None,
        "window_end": frame.window_end.isoformat() if frame.window_end else None,
        "detectors": detector_stats,
        "patterns": len(records),
        "patterns_by_status": by_status,
        "calibration": calibration,
        "suppressed_families": len(suppressed),
        "baseline_runs_before": int(baseline.get("runs") or 0),
        "ms": round((time.perf_counter() - started) * 1000, 1),
    }
    return EngineResult(
        run_id=run_id, tenant_id=tenant_id, records=records, detectors_run=detectors_run,
        kinds_run=sorted(kinds_run), stats=stats, baseline_delta=baseline_delta,
        schema=extraction.profile_summary(),
        observations_sample=extraction.candidate_observations(tenant_id, limit=200),
    )
