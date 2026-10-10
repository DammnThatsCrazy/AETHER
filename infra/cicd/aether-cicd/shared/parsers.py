"""
Aether CI/CD -- Tool Output Parsers
Parses JSON/text output from every CI tool into typed dicts.
No more hardcoded stub values -- each stage calls the right parser.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Parser result types
# --------------------------------------------------------------------------- #

@dataclass
class CoverageResult:
    pct: float
    total_tests: int
    passed: int
    failed: int
    skipped: int = 0


@dataclass
class VulnerabilityResult:
    critical: int
    high: int
    medium: int
    low: int


@dataclass
class SecretsResult:
    secrets_found: int
    details: list


@dataclass
class PerformanceResult:
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    rps: float
    total_requests: int
    failed_requests: int


# --------------------------------------------------------------------------- #
# Jest coverage  (coverage-summary.json)
# --------------------------------------------------------------------------- #

def parse_jest_coverage(json_str: str) -> CoverageResult:
    """
    Parse Jest coverage-summary.json.
    Expected structure: { "total": { "lines": { "pct": 93.2 }, ... }, ... }
    Falls back to 0.0 if parsing fails.
    """
    try:
        data = json.loads(json_str)
        total = data.get("total", {})
        lines = total.get("lines", {})
        pct = lines.get("pct", 0.0)
        # Jest summary doesn't include test counts; fill from other source
        return CoverageResult(pct=pct, total_tests=0, passed=0, failed=0)
    except (json.JSONDecodeError, KeyError, TypeError):
        return CoverageResult(pct=0.0, total_tests=0, passed=0, failed=0)


def parse_jest_results(json_str: str) -> CoverageResult:
    """
    Parse Jest --json output for test counts.
    Expected: { "numTotalTests": N, "numPassedTests": N, "numFailedTests": N, ... }
    """
    try:
        data = json.loads(json_str)
        total = data.get("numTotalTests", 0)
        passed = data.get("numPassedTests", 0)
        failed = data.get("numFailedTests", 0)
        skipped = data.get("numPendingTests", 0)
        return CoverageResult(pct=0.0, total_tests=total, passed=passed, failed=failed, skipped=skipped)
    except (json.JSONDecodeError, KeyError, TypeError):
        return CoverageResult(pct=0.0, total_tests=0, passed=0, failed=0)


# --------------------------------------------------------------------------- #
# pytest coverage  (coverage.json from pytest-cov)
# --------------------------------------------------------------------------- #

def parse_pytest_coverage(json_str: str) -> CoverageResult:
    """
    Parse pytest-cov JSON output.
    Expected: { "totals": { "percent_covered": 91.5, ... } }
    """
    try:
        data = json.loads(json_str)
        totals = data.get("totals", {})
        pct = totals.get("percent_covered", 0.0)
        return CoverageResult(pct=pct, total_tests=0, passed=0, failed=0)
    except (json.JSONDecodeError, KeyError, TypeError):
        return CoverageResult(pct=0.0, total_tests=0, passed=0, failed=0)


def parse_pytest_results(output: str) -> CoverageResult:
    """
    Parse pytest short summary text output.
    Looks for: "X passed, Y failed, Z skipped" or "X passed"
    """
    passed = failed = skipped = 0
    match = re.search(r"(\d+) passed", output)
    if match:
        passed = int(match.group(1))
    match = re.search(r"(\d+) failed", output)
    if match:
        failed = int(match.group(1))
    match = re.search(r"(\d+) skipped", output)
    if match:
        skipped = int(match.group(1))
    total = passed + failed + skipped
    return CoverageResult(pct=0.0, total_tests=total, passed=passed, failed=failed, skipped=skipped)


# --------------------------------------------------------------------------- #
# Snyk  (snyk test --json)
# --------------------------------------------------------------------------- #

def parse_snyk_json(json_str: str) -> VulnerabilityResult:
    """
    Parse Snyk JSON output.
    Expected: { "vulnerabilities": [ { "severity": "critical" | "high" | ... }, ... ] }
    """
    try:
        data = json.loads(json_str)
        vulns = data.get("vulnerabilities", [])
        counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for v in vulns:
            sev = v.get("severity", "low").lower()
            if sev in counts:
                counts[sev] += 1
        return VulnerabilityResult(**counts)
    except (json.JSONDecodeError, KeyError, TypeError):
        return VulnerabilityResult(critical=0, high=0, medium=0, low=0)


# --------------------------------------------------------------------------- #
# Trivy  (trivy fs --format json)
# --------------------------------------------------------------------------- #

def parse_trivy_json(json_str: str) -> VulnerabilityResult:
    """
    Parse Trivy JSON output.
    Expected: { "Results": [ { "Vulnerabilities": [ { "Severity": "CRITICAL" }, ... ] } ] }
    """
    try:
        data = json.loads(json_str)
        counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for result in data.get("Results", []):
            for vuln in result.get("Vulnerabilities", []):
                sev = vuln.get("Severity", "LOW").lower()
                if sev in counts:
                    counts[sev] += 1
        return VulnerabilityResult(**counts)
    except (json.JSONDecodeError, KeyError, TypeError):
        return VulnerabilityResult(critical=0, high=0, medium=0, low=0)


# --------------------------------------------------------------------------- #
# GitLeaks  (gitleaks detect --report-format json)
# --------------------------------------------------------------------------- #

def parse_gitleaks_json(json_str: str) -> SecretsResult:
    """
    Parse GitLeaks JSON report.
    Expected: [ { "Description": "...", "File": "...", "StartLine": N }, ... ]
    """
    try:
        findings = json.loads(json_str)
        if not isinstance(findings, list):
            findings = []
        return SecretsResult(
            secrets_found=len(findings),
            details=[
                {"file": f.get("File", ""), "description": f.get("Description", "")}
                for f in findings[:20]  # cap detail output
            ],
        )
    except (json.JSONDecodeError, TypeError):
        return SecretsResult(secrets_found=0, details=[])


# --------------------------------------------------------------------------- #
# k6  (k6 run --out json)
# --------------------------------------------------------------------------- #

def parse_k6_json(json_str: str) -> PerformanceResult:
    """
    Parse k6 end-of-test JSON summary.
    Expected: { "metrics": { "http_req_duration": { "values": { "p(50)": N, ... } } } }
    """
    try:
        data = json.loads(json_str)
        metrics = data.get("metrics", {})
        duration = metrics.get("http_req_duration", {}).get("values", {})
        reqs = metrics.get("http_reqs", {}).get("values", {})
        fails = metrics.get("http_req_failed", {}).get("values", {})
        return PerformanceResult(
            p50_ms=duration.get("p(50)", 0.0),
            p90_ms=duration.get("p(90)", 0.0),
            p95_ms=duration.get("p(95)", 0.0),
            p99_ms=duration.get("p(99)", 0.0),
            rps=reqs.get("rate", 0.0),
            total_requests=int(reqs.get("count", 0)),
            failed_requests=int(fails.get("count", 0)),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return PerformanceResult(
            p50_ms=0, p90_ms=0, p95_ms=0, p99_ms=0, rps=0, total_requests=0, failed_requests=0,
        )


# --------------------------------------------------------------------------- #
# Docker image size  (docker image inspect --format='{{.Size}}')
# --------------------------------------------------------------------------- #

def parse_docker_image_size(output: str) -> float:
    """Parse `docker image inspect --format='{{.Size}}'` output into MB."""
    try:
        size_bytes = int(output.strip())
        return size_bytes / (1024 * 1024)
    except (ValueError, TypeError):
        return 0.0


# --------------------------------------------------------------------------- #
# Lint error count (eslint --format json)
# --------------------------------------------------------------------------- #

def parse_eslint_json(json_str: str) -> int:
    """Parse ESLint JSON output and return total error count."""
    try:
        results = json.loads(json_str)
        return sum(r.get("errorCount", 0) for r in results)
    except (json.JSONDecodeError, TypeError):
        return 0


def parse_ruff_json(json_str: str) -> int:
    """Parse Ruff JSON output and return count of violations."""
    try:
        results = json.loads(json_str)
        if isinstance(results, list):
            return len(results)
        return 0
    except (json.JSONDecodeError, TypeError):
        return 0
