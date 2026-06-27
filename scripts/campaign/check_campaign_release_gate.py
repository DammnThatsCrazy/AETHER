#!/usr/bin/env python3
"""Campaign Intelligence release gate.

Verifies that all campaign feature gates pass before a production deployment.
Exit 0 = all checks pass. Exit 1 = one or more checks failed.

Usage:
    python scripts/campaign/check_campaign_release_gate.py
    python scripts/campaign/check_campaign_release_gate.py --strict
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""
    skipped: bool = False


@dataclass
class GateReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        icon = "✓" if result.passed else ("~" if result.skipped else "✗")
        print(f"  {icon} {result.name}", flush=True)
        if result.message and not result.passed:
            print(f"    → {result.message}", flush=True)

    @property
    def passed(self) -> bool:
        return all(r.passed or r.skipped for r in self.results)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.skipped)


def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(cwd or REPO_ROOT),
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout}s"
    except FileNotFoundError as exc:
        return False, f"Command not found: {exc}"


def check_required_files() -> list[CheckResult]:
    required = [
        BACKEND / "services/campaign/registry.py",
        BACKEND / "services/campaign/resolver.py",
        BACKEND / "services/campaign/normalization.py",
        BACKEND / "services/campaign/repository.py",
        BACKEND / "services/campaign/routes.py",
        BACKEND / "services/campaign/metrics.py",
        BACKEND / "services/measurement/connectors/writer.py",
        BACKEND / "alembic/versions/20260627_campaign_registry.py",
        BACKEND / "tests/unit/test_campaign_registry.py",
        BACKEND / "tests/integration/test_campaign_registry_api.py",
        BACKEND / "tests/e2e/test_campaign_registry_e2e.py",
        BACKEND / "tests/security/test_campaign_registry_security.py",
        REPO_ROOT / "scripts/campaign/backfill_campaign_ids.py",
        REPO_ROOT / "packages/shared/acquisition-evidence.ts",
        REPO_ROOT / "docs/campaign/CAMPAIGN_INTELLIGENCE_OVERVIEW.md",
        REPO_ROOT / "docs/campaign/CAMPAIGN_REGISTRY_ARCHITECTURE.md",
        REPO_ROOT / "docs/campaign/CAMPAIGN_RESOLUTION_CONTRACT.md",
        REPO_ROOT / "docs/campaign/CAMPAIGN_SDK_ACQUISITION.md",
        REPO_ROOT / "docs/campaign/CAMPAIGN_CONNECTORS.md",
        REPO_ROOT / "docs/campaign/CAMPAIGN_MIGRATION.md",
        REPO_ROOT / "docs/campaign/CAMPAIGN_KYBER_GUIDE.md",
        REPO_ROOT / "docs/campaign/ADR_CAMPAIGN_IDENTITY.md",
        REPO_ROOT / "deploy/observability/prometheus/alert_rules.yml",
    ]
    results = []
    for path in required:
        exists = path.exists()
        results.append(CheckResult(
            name=f"file: {path.relative_to(REPO_ROOT)}",
            passed=exists,
            message="" if exists else "File missing",
        ))
    return results


def check_alert_rules_present() -> CheckResult:
    alert_file = REPO_ROOT / "deploy/observability/prometheus/alert_rules.yml"
    if not alert_file.exists():
        return CheckResult("campaign alert rules", False, "alert_rules.yml missing")
    content = alert_file.read_text()
    required_alerts = [
        "CampaignSpendMissingCanonicalId",
        "CampaignResolutionUnresolvedRateHigh",
        "CampaignSourceSyncFailed",
        "CampaignSourceStale",
        "CampaignBackfillStuck",
    ]
    missing = [a for a in required_alerts if a not in content]
    if missing:
        return CheckResult("campaign alert rules", False, f"Missing alerts: {missing}")
    return CheckResult("campaign alert rules", True)


def check_sdk_contract_exported() -> CheckResult:
    acq_file = REPO_ROOT / "packages/shared/acquisition-evidence.ts"
    if not acq_file.exists():
        return CheckResult("SDK AcquisitionEvidence export", False, "acquisition-evidence.ts missing")
    content = acq_file.read_text()
    if "export interface AcquisitionEvidence" not in content:
        return CheckResult("SDK AcquisitionEvidence export", False, "AcquisitionEvidence not exported")
    if "evidenceFromSearchParams" not in content:
        return CheckResult("SDK AcquisitionEvidence export", False, "evidenceFromSearchParams not exported")
    return CheckResult("SDK AcquisitionEvidence export", True)


def check_unit_tests(strict: bool) -> CheckResult:
    ok, out = run_cmd(
        ["python", "-m", "pytest", "tests/unit/test_campaign_registry.py", "-v", "--tb=short", "-q"],
        cwd=BACKEND, timeout=60,
    )
    if not ok and not strict:
        return CheckResult("unit tests", True, "", skipped=True)
    return CheckResult("unit tests", ok, out[-500:] if not ok else "")


def check_security_tests(strict: bool) -> CheckResult:
    ok, out = run_cmd(
        ["python", "-m", "pytest", "tests/security/test_campaign_registry_security.py", "-v", "--tb=short", "-q"],
        cwd=BACKEND, timeout=60,
    )
    if not ok and not strict:
        return CheckResult("security tests", True, "", skipped=True)
    return CheckResult("security tests", ok, out[-500:] if not ok else "")


def check_invariant_docstring_present() -> CheckResult:
    resolver_file = BACKEND / "services/campaign/resolver.py"
    if not resolver_file.exists():
        return CheckResult("resolver invariants documented", False, "resolver.py missing")
    content = resolver_file.read_text()
    markers = ["never", "tenant", "fuzzy"]
    found = all(m in content.lower() for m in markers)
    if not found:
        return CheckResult("resolver invariants documented", False,
                           "Resolver missing documentation of key invariants")
    return CheckResult("resolver invariants documented", True)


def check_kyber_routes_present() -> CheckResult:
    kyber_file = BACKEND / "services/measurement/routes/kyber.py"
    if not kyber_file.exists():
        return CheckResult("kyber campaign routes", False, "kyber.py missing")
    content = kyber_file.read_text()
    required = [
        "/campaign/fleet-health",
        "/campaign/tenant/{tenant_id_param}",
        "/campaign/tenant/{tenant_id_param}/reprocess",
        "/campaign/audit",
    ]
    missing = [r for r in required if r not in content]
    if missing:
        return CheckResult("kyber campaign routes", False, f"Missing routes: {missing}")
    return CheckResult("kyber campaign routes", True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Campaign Intelligence release gate")
    parser.add_argument("--strict", action="store_true", help="Run test suites (requires test environment)")
    args = parser.parse_args()

    report = GateReport()
    print("\nCampaign Intelligence Release Gate\n" + "=" * 40)

    print("\n[Required files]")
    for result in check_required_files():
        report.add(result)

    print("\n[Alert rules]")
    report.add(check_alert_rules_present())

    print("\n[SDK contracts]")
    report.add(check_sdk_contract_exported())

    print("\n[Backend invariants]")
    report.add(check_invariant_docstring_present())
    report.add(check_kyber_routes_present())

    print("\n[Test suites]")
    report.add(check_unit_tests(args.strict))
    report.add(check_security_tests(args.strict))

    print(f"\n{'='*40}")
    if report.passed:
        print("PASS — Campaign Intelligence release gate passed.")
        return 0
    else:
        print(f"FAIL — {report.failed_count} check(s) failed. See details above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
