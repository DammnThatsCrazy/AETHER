#!/usr/bin/env python3
"""Validate local CI runtime evidence against the canonical suite registry.

The input is either a JSON array, a JSON object containing a ``runs`` array,
or JSONL with one run object per line. Each run must identify a registered
suite, its runtime in seconds, and the selector that chose it. No network
client or URL fetch is used: evidence is read from a local filesystem path.

The report includes deterministic p50/p95 runtime telemetry, selection counts
and frequency, selector breakdowns, outcomes, retries, cache hits, and hard
budget violations. A violation is reported when an observed sample or the
linear-interpolation p95 exceeds the suite's registry budget.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "config" / "test_suites.yaml"
DEFAULT_POLICY = ROOT / "config" / "ci_runtime_budgets.yaml"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RuntimeBudgetError(ValueError):
    """Runtime policy or evidence is malformed and cannot be trusted."""


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeBudgetError(f"{where} must be a mapping")
    return value


def _load_policy(path: str | Path) -> Mapping[str, Any]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    if not resolved.exists() or not resolved.is_file():
        raise RuntimeBudgetError(f"runtime policy does not exist: {resolved}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuntimeBudgetError(f"invalid runtime policy YAML: {exc}") from exc
    policy = _require_mapping(raw, "runtime policy")
    required = {
        "schema_version",
        "canonical_registry",
        "runtime_unit",
        "percentiles",
        "violation_policy",
        "evidence",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise RuntimeBudgetError(f"runtime policy missing key(s): {', '.join(missing)}")
    if policy["schema_version"] != 1:
        raise RuntimeBudgetError("runtime policy schema_version must be 1")
    if policy["canonical_registry"] != "config/test_suites.yaml":
        raise RuntimeBudgetError(
            "runtime policy canonical_registry must be config/test_suites.yaml"
        )
    if policy["runtime_unit"] != "seconds":
        raise RuntimeBudgetError("runtime policy runtime_unit must be 'seconds'")

    percentiles = _require_mapping(policy["percentiles"], "runtime policy.percentiles")
    if percentiles.get("p50") != 0.5 or percentiles.get("p95") != 0.95:
        raise RuntimeBudgetError("runtime policy must define p50=0.5 and p95=0.95")
    if percentiles.get("method") != "linear_interpolation":
        raise RuntimeBudgetError("runtime policy percentile method must be linear_interpolation")

    violation = _require_mapping(policy["violation_policy"], "runtime policy.violation_policy")
    if violation.get("compare_percentile") != "p95":
        raise RuntimeBudgetError("runtime policy must compare p95 budgets")
    if violation.get("compare_maximum_sample") is not True:
        raise RuntimeBudgetError("runtime policy must compare maximum samples")
    if violation.get("budget_field") != "hard_runtime_budget_seconds":
        raise RuntimeBudgetError(
            "runtime policy budget_field must be hard_runtime_budget_seconds"
        )

    evidence = _require_mapping(policy["evidence"], "runtime policy.evidence")
    if set(evidence.get("accepted_formats", [])) != {"json", "jsonl"}:
        raise RuntimeBudgetError("runtime policy must accept json and jsonl evidence")
    if set(evidence.get("required_fields", [])) != {"suite", "runtime_seconds", "selected_by"}:
        raise RuntimeBudgetError(
            "runtime policy required_fields must be suite, runtime_seconds, selected_by"
        )
    aliases = _require_mapping(evidence.get("aliases"), "runtime policy.evidence.aliases")
    if aliases.get("suite") != ["suite_id"] or aliases.get("runtime_seconds") != ["runtime"]:
        raise RuntimeBudgetError("runtime policy evidence aliases are invalid")
    return policy


def _local_path(path: str | Path) -> Path:
    raw = str(path)
    if "://" in raw:
        raise RuntimeBudgetError("evidence must be a local JSON or JSONL path; network URLs are not allowed")
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    if not resolved.exists() or not resolved.is_file():
        raise RuntimeBudgetError(f"evidence file does not exist: {resolved}")
    return resolved


def _records_from_json(raw: Any, source: Path) -> list[Mapping[str, Any]]:
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict) and isinstance(raw.get("runs"), list):
        records = raw["runs"]
    else:
        raise RuntimeBudgetError(f"{source}: JSON must be an array or an object with a 'runs' array")
    if not all(isinstance(record, dict) for record in records):
        raise RuntimeBudgetError(f"{source}: every evidence run must be a JSON object")
    return records


def load_evidence(path: str | Path) -> list[Mapping[str, Any]]:
    """Load local JSON or JSONL evidence without making network calls."""
    source = _local_path(path)
    suffix = source.suffix.lower()
    if suffix not in {".json", ".jsonl"}:
        raise RuntimeBudgetError(f"{source}: evidence extension must be .json or .jsonl")
    try:
        text = source.read_text(encoding="utf-8")
        if suffix == ".json":
            return _records_from_json(json.loads(text), source)
        records: list[Mapping[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeBudgetError(f"{source}:{line_number}: invalid JSONL: {exc}") from exc
            if not isinstance(record, dict):
                raise RuntimeBudgetError(f"{source}:{line_number}: run must be a JSON object")
            records.append(record)
        return records
    except json.JSONDecodeError as exc:
        raise RuntimeBudgetError(f"{source}: invalid JSON: {exc}") from exc
    except OSError as exc:
        raise RuntimeBudgetError(f"cannot read evidence {source}: {exc}") from exc


def percentile(values: Sequence[float], quantile: float) -> float:
    """Return a deterministic linear-interpolation percentile.

    The rank is ``quantile * (n - 1)``; this gives the usual median for an
    even-sized sample and clamps p0/p100 to the observed range.
    """
    if not values:
        raise RuntimeBudgetError("cannot calculate a percentile with no samples")
    if not 0 <= quantile <= 1:
        raise RuntimeBudgetError("percentile quantile must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    rank = quantile * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _finite_number(value: Any, where: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeBudgetError(f"{where} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (result < 0 if allow_zero else result <= 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise RuntimeBudgetError(f"{where} must be a finite {qualifier} number")
    return result


def _normalize_record(record: Mapping[str, Any], index: int) -> dict[str, Any]:
    where = f"evidence[{index}]"
    suite_id = record.get("suite", record.get("suite_id"))
    if not isinstance(suite_id, str) or not suite_id.strip():
        raise RuntimeBudgetError(f"{where}.suite must be a non-empty string")
    runtime = record.get("runtime_seconds", record.get("runtime"))
    runtime_seconds = _finite_number(runtime, f"{where}.runtime_seconds")
    selected_by = record.get("selected_by")
    if isinstance(selected_by, str) and selected_by.strip():
        selectors = [selected_by]
    elif isinstance(selected_by, list) and selected_by and all(
        isinstance(value, str) and value.strip() for value in selected_by
    ):
        selectors = list(selected_by)
    else:
        raise RuntimeBudgetError(f"{where}.selected_by must be a non-empty string or list of strings")
    outcome = record.get("outcome", "unknown")
    if not isinstance(outcome, str) or not outcome.strip():
        raise RuntimeBudgetError(f"{where}.outcome must be a non-empty string when provided")
    component = record.get("component", record.get("components", []))
    if isinstance(component, str):
        components = [component] if component.strip() else []
    elif isinstance(component, list) and all(isinstance(value, str) and value.strip() for value in component):
        components = list(component)
    else:
        raise RuntimeBudgetError(f"{where}.component(s) must be a string or list of strings")
    retry = record.get("retry", False)
    cache = record.get("cache", False)
    if not isinstance(retry, bool) or not isinstance(cache, bool):
        raise RuntimeBudgetError(f"{where}.retry and {where}.cache must be booleans")
    return {
        "suite": suite_id,
        "runtime_seconds": runtime_seconds,
        "selected_by": selectors,
        "outcome": outcome,
        "components": components,
        "retry": retry,
        "cache": cache,
    }


def build_runtime_report(
    records: Iterable[Mapping[str, Any]],
    suites: Sequence[Any],
    *,
    evidence_source: str | None = None,
) -> dict[str, Any]:
    """Build telemetry and violations for normalized or raw evidence records."""
    suite_by_id = {suite.id: suite for suite in suites}
    normalized = [_normalize_record(record, index) for index, record in enumerate(records)]
    unknown = sorted({record["suite"] for record in normalized} - set(suite_by_id))
    if unknown:
        raise RuntimeBudgetError(
            "evidence references unregistered suite(s): " + ", ".join(unknown)
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    global_selection = Counter()
    for record in normalized:
        grouped[record["suite"]].append(record)
        global_selection.update(record["selected_by"])

    suite_reports: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    total_runs = len(normalized)
    for suite_id in sorted(grouped):
        suite = suite_by_id[suite_id]
        suite_records = grouped[suite_id]
        runtimes = [record["runtime_seconds"] for record in suite_records]
        p50 = percentile(runtimes, 0.50)
        p95 = percentile(runtimes, 0.95)
        maximum = max(runtimes)
        hard_budget = suite.hard_runtime_budget_seconds
        violation_reasons = []
        if p95 > hard_budget:
            violation_reasons.append("p95_exceeds_hard_budget")
        if maximum > hard_budget:
            violation_reasons.append("sample_exceeds_hard_budget")
        suite_report = {
            "suite": suite_id,
            "components": sorted({component for record in suite_records for component in record["components"]}),
            "samples": len(runtimes),
            "p50_seconds": p50,
            "p95_seconds": p95,
            "maximum_seconds": maximum,
            "expected_runtime_seconds": suite.expected_runtime_seconds,
            "hard_runtime_budget_seconds": hard_budget,
            "budget_violation": bool(violation_reasons),
            "violation_reasons": violation_reasons,
            "selection_count": len(suite_records),
            "selection_frequency": len(suite_records) / total_runs if total_runs else 0.0,
            "selection_by": dict(sorted(Counter(selector for record in suite_records for selector in record["selected_by"]).items())),
            "outcomes": dict(sorted(Counter(record["outcome"] for record in suite_records).items())),
            "failure_yield": sum(record["outcome"] == "failed" for record in suite_records) / len(suite_records),
            "retry_count": sum(record["retry"] for record in suite_records),
            "cache_hit_count": sum(record["cache"] for record in suite_records),
        }
        suite_reports.append(suite_report)
        if violation_reasons:
            violations.append({
                "suite": suite_id,
                "hard_runtime_budget_seconds": hard_budget,
                "p95_seconds": p95,
                "maximum_seconds": maximum,
                "reasons": violation_reasons,
            })

    return {
        "evidence_source": evidence_source,
        "total_runs": total_runs,
        "selection": {
            "by": dict(sorted(global_selection.items())),
            "suite_counts": {
                suite_id: report["selection_count"] for suite_id, report in ((item["suite"], item) for item in suite_reports)
            },
        },
        "suites": suite_reports,
        "violations": violations,
        "valid": not violations,
    }


def validate(
    evidence_path: str | Path,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
    policy_path: str | Path = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Load local evidence and return a runtime-budget report."""
    _load_policy(policy_path)
    from scripts.lib.test_suites import load_suites

    registry = Path(registry_path)
    if not registry.is_absolute():
        registry = ROOT / registry
    suites = load_suites(registry)
    records = load_evidence(evidence_path)
    return build_runtime_report(records, suites, evidence_source=str(_local_path(evidence_path)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, nargs="?", help="local .json or .jsonl runtime evidence")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable JSON")
    parser.add_argument(
        "--check-registry",
        action="store_true",
        help="validate the runtime policy and suite metadata without runtime evidence",
    )
    args = parser.parse_args(argv)
    try:
        if args.check_registry:
            _load_policy(args.policy)
            from scripts.lib.test_suites import load_suites

            registry = Path(args.registry)
            if not registry.is_absolute():
                registry = ROOT / registry
            suites = load_suites(registry)
            print(json.dumps({"schema_version": 1, "status": "PASS", "suite_count": len(suites)}))
            return 0
        if args.evidence is None:
            parser.error("evidence is required unless --check-registry is supplied")
        report = validate(args.evidence, registry_path=args.registry, policy_path=args.policy)
    except (RuntimeBudgetError, OSError, ValueError) as exc:
        print(f"FAIL — CI runtime evidence: {exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"runtime evidence: {report['total_runs']} runs")
        for suite in report["suites"]:
            status = "VIOLATION" if suite["budget_violation"] else "ok"
            print(
                f"  {suite['suite']}: p50={suite['p50_seconds']:.2f}s "
                f"p95={suite['p95_seconds']:.2f}s selected={suite['selection_count']} "
                f"({status})"
            )
        print("selection by: " + json.dumps(report["selection"]["by"], sort_keys=True))
        if report["violations"]:
            print("FAIL — runtime budget violation(s):")
            for violation in report["violations"]:
                print(f"  - {violation['suite']}: {', '.join(violation['reasons'])}")
        else:
            print("runtime budgets OK")
    return 1 if report["violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
