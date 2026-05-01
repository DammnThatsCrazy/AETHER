"""
Aether CI/CD Pipeline -- Demo Runner
Demonstrates the full CI -> CD -> SDK Release pipeline.

Run:  python main.py
"""

from __future__ import annotations

import os
import sys

# Ensure package root is on sys.path for clean imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.pipeline_config import (
    CI_STAGES, CD_STAGES, BRANCH_CONFIG, AWS_ACCOUNTS,
    REPO_SERVICES, REPO_PACKAGES, TERRAFORM_CONFIG,
    NOTIFICATION_CONFIG, CACHE_CONFIG, CHANGE_DETECTION_CONFIG,
)
from quality_gates.gate import QualityGate
from stages.sdk.sdk_release import release_all_sdks, BumpType, PreRelease


def print_header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


# --------------------------------------------------------------------------- #
# 1. Pipeline Configuration
# --------------------------------------------------------------------------- #

def demo_pipeline_config() -> None:
    """Show the pipeline configuration."""
    print_header("PIPELINE CONFIGURATION")

    print("Git Branching (GitFlow):")
    print(f"  main:     {BRANCH_CONFIG.main}")
    print(f"  staging:  {BRANCH_CONFIG.staging}")
    print(f"  develop:  {BRANCH_CONFIG.develop}")
    print(f"  features: {BRANCH_CONFIG.feature_prefix}*")
    print(f"  hotfixes: {BRANCH_CONFIG.hotfix_prefix}*")
    print(f"  releases: {BRANCH_CONFIG.release_prefix}*")

    print(f"\nMonorepo -- {len(REPO_PACKAGES)} packages + {len(REPO_SERVICES)} services:")
    for path in REPO_PACKAGES:
        print(f"  pkg  {path}")
    for path in REPO_SERVICES:
        print(f"  svc  {path}")

    print(f"\nAWS Accounts ({len(AWS_ACCOUNTS)}):")
    for acc in AWS_ACCOUNTS:
        print(f"  {acc.name:22s} -> {acc.purpose}")

    print(f"\nCI Pipeline -- {len(CI_STAGES)} stages:")
    for s in CI_STAGES:
        parallel = f"  (parallel with stage {s.parallelisable_with})" if s.parallelisable_with else ""
        print(f"  {s.number}. {s.name:20s} gate: {s.quality_gate}{parallel}")

    print(f"\nCD Pipeline -- {len(CD_STAGES)} stages:")
    for s in CD_STAGES:
        traffic = f" ({s.traffic_pct}%)" if s.traffic_pct else ""
        approval = " [requires approval]" if s.requires_approval else ""
        print(f"  {s.number}. {s.name:22s} rollback: {s.rollback_trigger}{traffic}{approval}")

    print(f"\nTerraform modules: {', '.join(TERRAFORM_CONFIG.modules)}")
    print(f"Drift detection: {TERRAFORM_CONFIG.drift_detection_cron}")

    print("\nNotifications:")
    print(f"  CI channel:  {NOTIFICATION_CONFIG.slack_channel_ci}")
    print(f"  CD channel:  {NOTIFICATION_CONFIG.slack_channel_cd}")
    print(f"  Alerts:      {NOTIFICATION_CONFIG.slack_channel_alerts}")
    print(f"  On rollback: {NOTIFICATION_CONFIG.notify_on_rollback}")
    print(f"  On drift:    {NOTIFICATION_CONFIG.notify_on_drift}")

    print("\nCaching:")
    print(f"  Turbo remote cache:  {CACHE_CONFIG.turbo_remote_cache}")
    print(f"  Docker layer cache:  {CACHE_CONFIG.docker_layer_cache}")
    print(f"  ECR keep count:      {CACHE_CONFIG.ecr_lifecycle_keep_count}")

    print("\nChange Detection:")
    print(f"  Enabled:        {CHANGE_DETECTION_CONFIG.enabled}")
    print(f"  Base ref:       {CHANGE_DETECTION_CONFIG.base_ref}")
    print(f"  Always run:     {', '.join(CHANGE_DETECTION_CONFIG.always_run_paths)}")
    print(f"  Service paths:  {len(CHANGE_DETECTION_CONFIG.service_path_map)} mappings")


# --------------------------------------------------------------------------- #
# 2. Quality Gate Engine
# --------------------------------------------------------------------------- #

def demo_quality_gates() -> None:
    """Demonstrate the quality gate engine with realistic values."""
    print_header("QUALITY GATE ENGINE DEMO")

    gate = QualityGate()

    # Simulate all 8 CI gates + new gates
    gate.check_lint(error_count=0)
    gate.check_type_check(error_count=0)
    gate.check_unit_test(coverage=93.2, failures=0, total=847)
    gate.check_integration_test(contracts_passed=42, contracts_total=42, failures=0)
    gate.check_security_scan(critical=0, high=0, medium=2, low=5, secrets_found=0)
    gate.check_sbom(generated=True, components=312)
    gate.check_build(success=True, image_size_mb=245.0, build_time_seconds=180.0)
    gate.check_container_signing(signed=True, image="aether-ingestion:abc123")
    gate.check_e2e_test(critical_paths_passed=15, critical_paths_total=15, failures=0)
    gate.check_performance_test(p99_latency_ms=142.0, memory_leak_detected=False, rps=2500.0)

    # Simulate CD gates
    gate.check_smoke_test(
        health_checks_passed=1, health_checks_total=1,
        api_flows_passed=7, api_flows_total=7,
    )
    gate.check_canary(error_rate_pct=0.2, p99_latency_ms=180.0)

    gate.print_summary()

    # Failure scenario
    print("\n  --- Failure scenario ---")
    fail_gate = QualityGate()
    fail_gate.check_unit_test(coverage=85.0, failures=3, total=847)
    fail_gate.check_security_scan(critical=1, high=2, medium=5, low=10, secrets_found=1)
    fail_gate.check_sbom(generated=False)
    fail_gate.print_summary()


# --------------------------------------------------------------------------- #
# 3. SDK Release
# --------------------------------------------------------------------------- #

def demo_sdk_release() -> None:
    """Demonstrate the SDK release pipeline with dry-run and pre-release."""
    print_header("SDK RELEASE PIPELINE DEMO")

    # Stable release (dry-run)
    results = release_all_sdks(
        current_versions={
            "web": "1.2.3",
            "ios": "1.2.3",
            "android": "1.2.3",
            "react_native": "1.2.3",
        },
        bump=BumpType.MINOR,
        commit_sha="abc123def456",
        dry_run=True,
    )

    # Beta pre-release (single platform, dry-run)
    print("\n  --- Single platform beta release ---")
    beta_results = release_all_sdks(
        current_versions={"web": "1.3.0"},
        bump=BumpType.PATCH,
        commit_sha="def789abc012",
        pre_release=PreRelease.BETA,
        platforms=["web"],
        dry_run=True,
    )


# --------------------------------------------------------------------------- #
# 4. Change Detection
# --------------------------------------------------------------------------- #

def demo_change_detection() -> None:
    """Demonstrate monorepo change detection."""
    print_header("CHANGE DETECTION DEMO")

    from shared.change_detect import detect_changed_services

    # Simulate specific service changes
    print("Scenario 1: Only ingestion + identity changed")
    affected = detect_changed_services(
        changed_files=[
            "services/ingestion/src/handler.ts",
            "services/identity/src/profile.ts",
            "services/identity/tests/profile.test.ts",
        ]
    )
    print(f"  Affected: {sorted(affected)}\n")

    # Simulate global change
    print("Scenario 2: Config changed (triggers full pipeline)")
    affected = detect_changed_services(
        changed_files=[
            "config/pipeline_config.py",
            "services/ingestion/src/handler.ts",
        ]
    )
    print(f"  Affected: {sorted(affected)}\n")

    # Simulate no changes
    print("Scenario 3: Only docs changed (no service match)")
    affected = detect_changed_services(
        changed_files=["README.md", "docs/architecture.md"]
    )
    print(f"  Affected: {sorted(affected)}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    print_header("Aether CI/CD PIPELINE -- FULL DEMO")

    # 1. Configuration overview
    demo_pipeline_config()

    # 2. Quality gate engine
    demo_quality_gates()

    # 3. Change detection
    demo_change_detection()

    # 4. SDK release pipeline
    demo_sdk_release()

    # 5. Summary
    print_header("PIPELINE COMPONENTS SUMMARY")
    print("  \u2713 Pipeline Config    -- 8 CI stages, 6 CD stages, quality thresholds")
    print("  \u2713 Quality Gates      -- Automated pass/fail for every stage + SBOM + signing")
    print("  \u2713 Shared Runner      -- Single _run_cmd, parsers, notifier (zero duplication)")
    print("  \u2713 Change Detection   -- Monorepo-aware selective builds")
    print("  \u2713 CI Stage Scripts   -- Lint, type check, unit test, integration,")
    print("                         security scan (+ SBOM), build (+ cosign), E2E, perf")
    print("  \u2713 CD Stage Scripts   -- Staging deploy, smoke test, canary (5%),")
    print("                         canary validation, progressive rollout, post-verify")
    print("  \u2713 SDK Release        -- Web (npm+CDN), iOS (CocoaPods+SPM),")
    print("                         Android (Maven), React Native (npm)")
    print("                         + dry-run mode + pre-release (alpha/beta/rc)")
    print("  \u2713 GitHub Actions     -- ci.yml (parallel lint+security, change detection,")
    print("                         Docker layer cache, cosign, SBOM)")
    print("                         cd.yml (approval gates, real ALB weights, rollback)")
    print("                         sdk-release.yml (parallel SDKs, dry-run, pre-release)")
    print("                         infrastructure.yml (cost estimation, sequential apply,")
    print("                         per-env state isolation, drift detection)")
    print("  \u2713 Terraform          -- ECS module with log groups, ECR lifecycle,")
    print("                         IAM policies, secrets, HTTP->HTTPS redirect,")
    print("                         memory scaling, canary TGs, circuit breaker")
    print("  \u2713 Notifications      -- Slack + PagerDuty for CI/CD/rollback/drift")
    print("  \u2713 Rollback           -- Automatic on any gate failure, captures previous TDs")
    print("  \u2713 Drift Detection    -- Daily Terraform drift checks with Slack alerts")
    print()


if __name__ == "__main__":
    main()
