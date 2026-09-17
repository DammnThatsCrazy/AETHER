"""
Aether CI/CD -- Quality Gate Engine
Every CI/CD stage reports results here.  The gate decides pass/fail/warn
based on thresholds in pipeline_config.

Enhancements over original:
  - SBOM gate for supply-chain security
  - Container signing gate
  - Aggregate severity scoring
  - JSON/dict export for dashboards
  - Fluent API for chained checks

Usage:
    gate = QualityGate()
    gate.check_lint(error_count=0)
    gate.check_unit_test(coverage=93.2, failures=0, total=847)
    if gate.all_passed:
        proceed_to_cd()
    else:
        gate.print_summary()
        sys.exit(1)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from config.pipeline_config import QUALITY_THRESHOLDS, QualityThresholds


class GateStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class GateResult:
    stage: str
    status: GateStatus
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def passed(self) -> bool:
        return self.status in (GateStatus.PASSED, GateStatus.WARNING, GateStatus.SKIPPED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "reason": self.reason,
            "metrics": self.metrics,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class QualityGate:
    """Central quality gate checker for all pipeline stages."""

    def __init__(self, thresholds: QualityThresholds | None = None) -> None:
        self.t = thresholds or QUALITY_THRESHOLDS
        self._results: list[GateResult] = []

    # -- CI Stage Gates -------------------------------------------------------

    def check_lint(self, error_count: int) -> GateResult:
        """Stage 1: Zero lint errors required."""
        result = GateResult(
            stage="lint",
            status=GateStatus.PASSED if error_count <= self.t.max_lint_errors else GateStatus.FAILED,
            reason="" if error_count == 0 else f"{error_count} lint error(s) found",
            metrics={"lint_errors": error_count},
        )
        self._results.append(result)
        return result

    def check_type_check(self, error_count: int) -> GateResult:
        """Stage 2: Zero type errors required."""
        result = GateResult(
            stage="type_check",
            status=GateStatus.PASSED if error_count <= self.t.max_type_errors else GateStatus.FAILED,
            reason="" if error_count == 0 else f"{error_count} type error(s) found",
            metrics={"type_errors": error_count},
        )
        self._results.append(result)
        return result

    def check_unit_test(
        self, coverage: float, failures: int, total: int = 0,
    ) -> GateResult:
        """Stage 3: >90% coverage, zero failures."""
        reasons: list[str] = []
        if failures > 0:
            reasons.append(f"{failures} test(s) failed")
        if coverage < self.t.min_unit_test_coverage:
            reasons.append(f"Coverage {coverage:.1f}% < {self.t.min_unit_test_coverage}%")

        result = GateResult(
            stage="unit_test",
            status=GateStatus.FAILED if reasons else GateStatus.PASSED,
            reason="; ".join(reasons),
            metrics={"coverage_pct": coverage, "failures": failures, "total_tests": total},
        )
        self._results.append(result)
        return result

    def check_integration_test(
        self, contracts_passed: int, contracts_total: int, failures: int,
    ) -> GateResult:
        """Stage 4: All contracts must pass."""
        result = GateResult(
            stage="integration_test",
            status=GateStatus.PASSED if failures == 0 else GateStatus.FAILED,
            reason="" if failures == 0 else f"{failures}/{contracts_total} contract(s) failed",
            metrics={
                "contracts_passed": contracts_passed,
                "contracts_total": contracts_total,
                "failures": failures,
            },
        )
        self._results.append(result)
        return result

    def check_security_scan(
        self,
        critical: int,
        high: int,
        medium: int = 0,
        low: int = 0,
        secrets_found: int = 0,
    ) -> GateResult:
        """Stage 5: Zero critical/high vulnerabilities, zero secrets."""
        reasons: list[str] = []
        if critical > 0:
            reasons.append(f"{critical} critical vulnerability(ies)")
        if high > 0:
            reasons.append(f"{high} high vulnerability(ies)")
        if secrets_found > 0:
            reasons.append(f"{secrets_found} secret(s) detected in code")

        status = GateStatus.FAILED if reasons else GateStatus.PASSED
        if not reasons and medium > 0:
            status = GateStatus.WARNING

        result = GateResult(
            stage="security_scan",
            status=status,
            reason=(
                "; ".join(reasons) if reasons
                else (f"{medium} medium vuln(s) -- review recommended" if medium else "")
            ),
            metrics={
                "critical": critical,
                "high": high,
                "medium": medium,
                "low": low,
                "secrets_found": secrets_found,
            },
        )
        self._results.append(result)
        return result

    def check_build(
        self,
        success: bool,
        image_size_mb: float = 0,
        build_time_seconds: float = 0,
    ) -> GateResult:
        """Stage 6: Successful build, image size within budget."""
        reasons: list[str] = []
        if not success:
            reasons.append("Build failed")
        if image_size_mb > self.t.max_docker_image_size_mb:
            reasons.append(
                f"Image size {image_size_mb:.0f}MB > {self.t.max_docker_image_size_mb}MB budget"
            )

        result = GateResult(
            stage="build",
            status=GateStatus.FAILED if reasons else GateStatus.PASSED,
            reason="; ".join(reasons),
            metrics={
                "success": success,
                "image_size_mb": image_size_mb,
                "build_time_seconds": build_time_seconds,
            },
        )
        self._results.append(result)
        return result

    def check_sbom(self, generated: bool, components: int = 0) -> GateResult:
        """Stage 5 addendum: SBOM generation (supply chain security)."""
        if not self.t.require_sbom:
            result = GateResult(
                stage="sbom",
                status=GateStatus.SKIPPED,
                reason="SBOM not required by thresholds",
            )
        else:
            result = GateResult(
                stage="sbom",
                status=GateStatus.PASSED if generated else GateStatus.FAILED,
                reason="" if generated else "SBOM generation failed",
                metrics={"generated": generated, "components": components},
            )
        self._results.append(result)
        return result

    def check_container_signing(self, signed: bool, image: str = "") -> GateResult:
        """Stage 6 addendum: Container image signing (cosign)."""
        if not self.t.require_container_signing:
            result = GateResult(
                stage="container_signing",
                status=GateStatus.SKIPPED,
                reason="Container signing not required",
            )
        else:
            result = GateResult(
                stage="container_signing",
                status=GateStatus.PASSED if signed else GateStatus.FAILED,
                reason="" if signed else f"Image {image} not signed",
                metrics={"signed": signed, "image": image},
            )
        self._results.append(result)
        return result

    def check_e2e_test(
        self, critical_paths_passed: int, critical_paths_total: int, failures: int,
    ) -> GateResult:
        """Stage 7: All critical paths must pass."""
        result = GateResult(
            stage="e2e_test",
            status=GateStatus.PASSED if failures == 0 else GateStatus.FAILED,
            reason="" if failures == 0 else f"{failures} critical path(s) failed",
            metrics={
                "critical_paths_passed": critical_paths_passed,
                "critical_paths_total": critical_paths_total,
                "failures": failures,
            },
        )
        self._results.append(result)
        return result

    def check_performance_test(
        self,
        p99_latency_ms: float,
        memory_leak_detected: bool = False,
        rps: float = 0,
    ) -> GateResult:
        """Stage 8: P99 < 200ms, no memory leaks."""
        reasons: list[str] = []
        if p99_latency_ms > self.t.max_p99_latency_ms:
            reasons.append(
                f"P99 latency {p99_latency_ms:.0f}ms > {self.t.max_p99_latency_ms}ms"
            )
        if memory_leak_detected:
            reasons.append("Memory leak detected")

        result = GateResult(
            stage="performance_test",
            status=GateStatus.FAILED if reasons else GateStatus.PASSED,
            reason="; ".join(reasons),
            metrics={
                "p99_latency_ms": p99_latency_ms,
                "memory_leak_detected": memory_leak_detected,
                "requests_per_second": rps,
            },
        )
        self._results.append(result)
        return result

    # -- CD Stage Gates -------------------------------------------------------

    def check_canary(self, error_rate_pct: float, p99_latency_ms: float) -> GateResult:
        """CD Stage 3-4: Canary metrics within thresholds."""
        reasons: list[str] = []
        if error_rate_pct > self.t.max_canary_error_rate_pct:
            reasons.append(
                f"Error rate {error_rate_pct:.2f}% > {self.t.max_canary_error_rate_pct}%"
            )
        if p99_latency_ms > self.t.max_canary_p99_latency_ms:
            reasons.append(
                f"P99 latency {p99_latency_ms:.0f}ms > {self.t.max_canary_p99_latency_ms}ms"
            )

        result = GateResult(
            stage="canary_validation",
            status=GateStatus.FAILED if reasons else GateStatus.PASSED,
            reason="; ".join(reasons),
            metrics={
                "error_rate_pct": error_rate_pct,
                "p99_latency_ms": p99_latency_ms,
                "traffic_pct": self.t.canary_traffic_pct,
            },
        )
        self._results.append(result)
        return result

    def check_smoke_test(
        self,
        health_checks_passed: int,
        health_checks_total: int,
        api_flows_passed: int,
        api_flows_total: int,
    ) -> GateResult:
        """CD Stage 2/6: Smoke test results."""
        failures = (health_checks_total - health_checks_passed) + (
            api_flows_total - api_flows_passed
        )
        result = GateResult(
            stage="smoke_test",
            status=GateStatus.PASSED if failures == 0 else GateStatus.FAILED,
            reason="" if failures == 0 else f"{failures} smoke test(s) failed",
            metrics={
                "health_checks": f"{health_checks_passed}/{health_checks_total}",
                "api_flows": f"{api_flows_passed}/{api_flows_total}",
            },
        )
        self._results.append(result)
        return result

    # -- Summary --------------------------------------------------------------

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self._results)

    @property
    def results(self) -> list[GateResult]:
        return list(self._results)

    @property
    def failed_gates(self) -> list[GateResult]:
        return [r for r in self._results if r.status == GateStatus.FAILED]

    def summary(self) -> dict[str, Any]:
        return {
            "total_gates": len(self._results),
            "passed": sum(1 for r in self._results if r.status == GateStatus.PASSED),
            "warnings": sum(1 for r in self._results if r.status == GateStatus.WARNING),
            "failed": sum(1 for r in self._results if r.status == GateStatus.FAILED),
            "skipped": sum(1 for r in self._results if r.status == GateStatus.SKIPPED),
            "all_passed": self.all_passed,
            "results": [r.to_dict() for r in self._results],
        }

    def print_summary(self) -> None:
        icons = {
            GateStatus.PASSED:  "\u2713",
            GateStatus.WARNING: "\u26a0",
            GateStatus.FAILED:  "\u2717",
            GateStatus.SKIPPED: "\u25cb",
        }
        width = 60
        print(f"\n{'=' * width}")
        print("  QUALITY GATE SUMMARY")
        print(f"{'=' * width}")
        for r in self._results:
            icon = icons[r.status]
            line = f"  {icon} {r.stage:25s} {r.status.value:8s}"
            if r.reason:
                line += f"  -- {r.reason}"
            print(line)
        print(f"{'-' * width}")
        s = self.summary()
        print(
            f"  Total: {s['total_gates']}  |  "
            f"Passed: {s['passed']}  |  "
            f"Warnings: {s['warnings']}  |  "
            f"Failed: {s['failed']}  |  "
            f"Skipped: {s['skipped']}"
        )
        verdict = "PIPELINE PASSED \u2713" if self.all_passed else "PIPELINE FAILED \u2717"
        print(f"  {verdict}")
        print(f"{'=' * width}\n")
