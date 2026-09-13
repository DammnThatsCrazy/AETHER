"""Fail-closed CI performance policy and critical-path calculations.

This module records observable timing and evaluates targets without claiming a
p50/p95 until the policy sample threshold is met.  It is intentionally local:
it does not publish telemetry or make selection decisions.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "config" / "ci_performance_policy.yaml"
STAGE_FIELDS = (
    "queue_seconds",
    "checkout_seconds",
    "dependency_setup_seconds",
    "cache_restore_seconds",
    "test_seconds",
    "build_seconds",
    "artifact_upload_seconds",
    "candidate_verification_seconds",
    "disposition_seconds",
    "total_job_seconds",
)


class PerformancePolicyError(ValueError):
    """The CI performance policy or timing evidence is invalid."""


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PerformancePolicyError(f"{where} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise PerformancePolicyError(f"{where} must be a finite non-negative number")
    return result


def load_policy(path: str | Path = DEFAULT_POLICY) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PerformancePolicyError(f"cannot read performance policy {resolved}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PerformancePolicyError("performance policy must be a mapping")
    required = {"schema_version", "canonical_source", "sample_threshold", "runtime_unit", "stages", "pr_classes", "disposition"}
    missing = sorted(required - set(raw))
    if missing:
        raise PerformancePolicyError("performance policy missing key(s): " + ", ".join(missing))
    if raw["schema_version"] != 1 or raw["canonical_source"] != "config/ci_performance_policy.yaml":
        raise PerformancePolicyError("performance policy identity is invalid")
    if raw["runtime_unit"] != "seconds" or not isinstance(raw["sample_threshold"], int) or raw["sample_threshold"] < 20:
        raise PerformancePolicyError("performance policy requires seconds and sample_threshold >= 20")
    for stage, values in raw["stages"].items():
        if not isinstance(values, dict) or _number(values.get("target_p95_seconds"), f"stages.{stage}.target_p95_seconds") <= 0:
            raise PerformancePolicyError(f"stages.{stage} must define a positive target_p95_seconds")
    for pr_class, values in raw["pr_classes"].items():
        if not isinstance(values, dict) or not any(key in values for key in ("target_p50_seconds", "target_p95_seconds")):
            raise PerformancePolicyError(f"pr_classes.{pr_class} must define a latency target")
        for key in ("target_p50_seconds", "target_p95_seconds"):
            if key in values and _number(values[key], f"pr_classes.{pr_class}.{key}") <= 0:
                raise PerformancePolicyError(f"pr_classes.{pr_class}.{key} must be positive")
    disposition = raw["disposition"]
    expected = {"initial_breach_status", "block_on_breach", "insufficient_samples_status", "measured_status"}
    if not isinstance(disposition, dict) or not expected <= set(disposition) or not isinstance(disposition["block_on_breach"], bool):
        raise PerformancePolicyError("performance policy disposition is invalid")
    return raw


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = quantile * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def pr_class(plan: Mapping[str, Any]) -> str:
    scopes = set(plan.get("global_scopes", []))
    build = plan.get("build", {}) if isinstance(plan.get("build", {}), dict) else {}
    domains = set(plan.get("domains", []))
    if "verification_control_plane" in scopes or plan.get("risk") in {"R4", "R5"}:
        return "architecture"
    if len(plan.get("selected_components", [])) > 1 or len(scopes) > 1:
        return "moderate_cross_component"
    if build.get("node_required") and not build.get("backend_image"):
        return "isolated_frontend"
    if build.get("backend_image") or "backend" in domains:
        return "isolated_backend"
    return "ordinary_pr"


def _job_duration(record: Mapping[str, Any]) -> float:
    if "total_job_seconds" in record:
        return _number(record["total_job_seconds"], "job.total_job_seconds")
    return sum(_number(record.get(field, 0), f"job.{field}") for field in STAGE_FIELDS[:-1])


def build_performance_evidence(
    plan: Mapping[str, Any],
    jobs: Iterable[Mapping[str, Any]],
    *,
    policy: Mapping[str, Any] | None = None,
    stage_seconds: Mapping[str, float] | None = None,
    historical_samples: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    policy = dict(policy or load_policy())
    records = [dict(job) for job in jobs]
    for job in records:
        for field in STAGE_FIELDS:
            if field in job:
                _number(job[field], f"job.{field}")
    stage_seconds = dict(stage_seconds or {})
    test_path = max((_job_duration(job) for job in records if job.get("stage") in {"suite_worker", "test", "control_prerequisites"}), default=0.0)
    build_path = max((_job_duration(job) for job in records if job.get("stage") == "build"), default=0.0)
    universal = max((_job_duration(job) for job in records if job.get("stage") == "universal_fast"), default=0.0)
    classifier = _number(stage_seconds.get("classifier_seconds", 0), "classifier_seconds")
    candidate = _number(stage_seconds.get("candidate_verification_seconds", 0), "candidate_verification_seconds")
    disposition = _number(stage_seconds.get("disposition_seconds", 0), "disposition_seconds")
    parallel_path = max(universal, test_path, build_path)
    critical_path = classifier + parallel_path + candidate + disposition
    total_authority = classifier + sum(_job_duration(job) for job in records) + candidate + disposition
    slowest = max(records, key=_job_duration, default={})
    sample_count = len(historical_samples)
    current_sample = {
        "critical_path_seconds": critical_path,
        "total_authority_seconds": total_authority,
        "pr_class": pr_class(plan),
    }
    samples = [*historical_samples, current_sample]
    threshold = int(policy["sample_threshold"])
    target = policy["pr_classes"].get(current_sample["pr_class"], policy["pr_classes"]["ordinary_pr"])
    measured_p50 = percentile([float(item["critical_path_seconds"]) for item in samples], 0.50) if len(samples) >= threshold else None
    measured_p95 = percentile([float(item["critical_path_seconds"]) for item in samples], 0.95) if len(samples) >= threshold else None
    degraded = critical_path > float(target.get("target_p95_seconds", float("inf")))
    status = policy["disposition"]["initial_breach_status"] if degraded else (
        policy["disposition"]["measured_status"] if measured_p95 is not None else policy["disposition"]["insufficient_samples_status"]
    )
    return {
        "schema_version": 1,
        "policy": "config/ci_performance_policy.yaml",
        "performance_status": status,
        "sample_count": len(samples),
        "sample_threshold": threshold,
        "measured": measured_p95 is not None,
        "claims_allowed": measured_p95 is not None,
        "pr_class": current_sample["pr_class"],
        "target_p50_seconds": target.get("target_p50_seconds"),
        "target_p95_seconds": target.get("target_p95_seconds"),
        "p50_seconds": measured_p50,
        "p95_seconds": measured_p95,
        "classifier_seconds": classifier,
        "universal_fast_seconds": universal,
        "test_critical_path_seconds": test_path,
        "build_critical_path_seconds": build_path,
        "candidate_verification_seconds": candidate,
        "disposition_seconds": disposition,
        "critical_path_seconds": critical_path,
        "total_authority_seconds": total_authority,
        "slowest_job": slowest.get("job", slowest.get("suite", "none")),
        "selected_suite_count": int(plan.get("selected_suite_count", 0)),
        "selected_component_count": int(plan.get("selected_component_count", 0)),
        "runner_count": len(records),
        "backend_image_selected": bool((plan.get("build") or {}).get("backend_image")),
        "risk_class": str(plan.get("risk", "R0")),
        "lane": str(plan.get("lane", "fast")),
        "global_scope": ",".join(sorted(plan.get("global_scopes", []))) or "none",
        "degraded_non_blocking": degraded and not bool(policy["disposition"]["block_on_breach"]),
    }


__all__ = ["DEFAULT_POLICY", "PerformancePolicyError", "build_performance_evidence", "load_policy", "percentile", "pr_class"]
