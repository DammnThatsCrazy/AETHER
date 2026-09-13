"""
Aether CI/CD Pipeline -- Central Configuration
Single source of truth for environments, stages, thresholds, notifications,
caching, and change detection across the entire pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# ENVIRONMENTS
# --------------------------------------------------------------------------- #

class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"
    DEMO = "demo"


@dataclass(frozen=True)
class AWSAccount:
    name: str
    account_id: str
    purpose: str
    environment: str
    region: str = "us-east-1"


AWS_ACCOUNTS = [
    AWSAccount("aether-dev",        "111111111111", "Development and testing",         "dev"),
    AWSAccount("aether-staging",    "222222222222", "Pre-production validation",        "staging"),
    AWSAccount("aether-production", "333333333333", "Live customer traffic",            "production"),
    AWSAccount("aether-data",       "444444444444", "Data lake and ML training",        "data"),
    AWSAccount("aether-security",   "555555555555", "Centralized logging and security", "security"),
    AWSAccount("aether-demo",       "666666666666", "Sales and BD demo environment",   "demo"),
]


# --------------------------------------------------------------------------- #
# GIT BRANCHING STRATEGY  (GitFlow)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BranchConfig:
    main: str = "main"
    staging: str = "staging"
    develop: str = "develop"
    demo: str = "demo"
    feature_prefix: str = "feature/"
    hotfix_prefix: str = "hotfix/"
    release_prefix: str = "release/"


BRANCH_CONFIG = BranchConfig()


# --------------------------------------------------------------------------- #
# MONOREPO STRUCTURE  (Turborepo)
# --------------------------------------------------------------------------- #

REPO_PACKAGES: Dict[str, Dict[str, str]] = {
    "packages/web":              {"lang": "typescript", "tool": "esbuild"},
    "packages/ios":              {"lang": "swift",      "tool": "xcodebuild"},
    "packages/android":          {"lang": "kotlin",     "tool": "gradle"},
    "packages/react-native":     {"lang": "typescript", "tool": "metro"},
    "packages/shared":           {"lang": "typescript", "tool": "esbuild"},
}

REPO_SERVICES: Dict[str, Dict[str, str]] = {
    "services/backend/services/ingestion":    {"lang": "python", "runtime": "python", "tool": "docker"},
    "services/backend/services/identity":     {"lang": "python", "runtime": "python", "tool": "docker"},
    "services/backend/services/analytics":    {"lang": "python", "runtime": "python", "tool": "docker"},
    "services/backend/services/ml_serving":   {"lang": "python", "runtime": "python", "tool": "docker"},
    "services/backend/services/agent":        {"lang": "python", "runtime": "python", "tool": "docker"},
    "services/backend/services/campaign":     {"lang": "python", "runtime": "python", "tool": "docker"},
    "services/backend/services/consent":      {"lang": "python", "runtime": "python", "tool": "docker"},
    "services/backend/services/notification": {"lang": "python", "runtime": "python", "tool": "docker"},
    "services/backend/services/admin":        {"lang": "python", "runtime": "python", "tool": "docker"},
}

REPO_OTHER: Dict[str, str] = {
    "deploy/aws/terraform/": "Terraform IaC for all AWS resources",
    "services/ml/":          "ML training pipelines, serving, and model configs",
    "frontend/aether/":      "Customer-facing React application",
}


# --------------------------------------------------------------------------- #
# CI PIPELINE -- 8 STAGES
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CIStage:
    number: int
    name: str
    actions: str
    quality_gate: str
    tools: List[str]
    timeout_minutes: int = 15
    required: bool = True
    parallelisable_with: List[int] = field(default_factory=list)


CI_STAGES = [
    CIStage(1, "lint",
        "Code style enforcement, import ordering, dead code detection",
        "Zero lint errors",
        ["eslint", "swiftlint", "ktlint", "black", "ruff"],
        timeout_minutes=5,
        parallelisable_with=[5]),      # lint + security scan can run in parallel
    CIStage(2, "type_check",
        "Static type verification across all TypeScript/Python services",
        "Zero type errors",
        ["tsc --noEmit", "mypy --strict"],
        timeout_minutes=5),
    CIStage(3, "unit_test",
        "Isolated component tests with mocked dependencies",
        ">90% coverage, zero failures",
        ["jest", "xctest", "junit", "pytest"],
        timeout_minutes=15),
    CIStage(4, "integration_test",
        "Service-to-service contract tests, database interaction tests",
        "All contracts pass",
        ["supertest", "testcontainers", "localstack"],
        timeout_minutes=20),
    CIStage(5, "security_scan",
        "Dependency vulnerability check, SAST, secret detection, SBOM",
        "Zero critical/high vulnerabilities, zero secrets",
        ["snyk", "codeql", "gitleaks", "trivy", "syft"],
        timeout_minutes=10,
        parallelisable_with=[1]),
    CIStage(6, "build",
        "Compile, bundle, containerize, sign all artifacts",
        "Successful build, size within budget",
        ["docker", "esbuild", "gradle", "xcodebuild", "cosign"],
        timeout_minutes=15),
    CIStage(7, "e2e_test",
        "Full system integration tests against staging environment",
        "All critical paths pass",
        ["playwright", "detox", "k6"],
        timeout_minutes=30),
    CIStage(8, "performance_test",
        "Load testing, latency benchmarking, memory profiling",
        "P99 < 200ms, no memory leaks",
        ["k6", "artillery", "clinic.js"],
        timeout_minutes=30),
]


# --------------------------------------------------------------------------- #
# CD PIPELINE -- 6 STAGES
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CDStage:
    number: int
    name: str
    actions: str
    rollback_trigger: str
    traffic_pct: Optional[int] = None
    validation_minutes: int = 5
    requires_approval: bool = False


CD_STAGES = [
    CDStage(1, "staging_deploy",
        "Deploy all services to staging via Terraform + ECS",
        "Any E2E test failure"),
    CDStage(2, "staging_smoke",
        "Automated smoke tests: health checks, critical API flows",
        "Any smoke test failure",
        validation_minutes=5),
    CDStage(3, "canary_deploy",
        "Deploy to 5% production traffic via weighted target groups",
        "Error rate > 1%, latency P99 > 500ms",
        traffic_pct=5,
        requires_approval=True),
    CDStage(4, "canary_validation",
        "Monitor canary metrics for 15 minutes",
        "Anomaly detection trigger",
        traffic_pct=5,
        validation_minutes=15),
    CDStage(5, "progressive_rollout",
        "Increase to 25%, 50%, 100% with 5-minute validation windows",
        "Any metric regression",
        traffic_pct=100,
        validation_minutes=15),
    CDStage(6, "post_deploy_verify",
        "Full production smoke test, dashboard verification, alert check",
        "Critical alert within 30 minutes",
        traffic_pct=100,
        validation_minutes=30),
]


# --------------------------------------------------------------------------- #
# DEMO CD PIPELINE -- 3 STAGES (simplified, no canary/rollout)
# --------------------------------------------------------------------------- #

DEMO_CD_STAGES = [
    CDStage(1, "demo_deploy",
        "Deploy all services to demo via Terraform + ECS",
        "Any deployment failure",
        requires_approval=False),
    CDStage(2, "demo_smoke",
        "Health checks + critical API flow validation",
        "Any smoke test failure",
        validation_minutes=3),
    CDStage(3, "demo_seed",
        "Seed demo environment with realistic sample data",
        "Seed script failure",
        validation_minutes=2),
]


# --------------------------------------------------------------------------- #
# QUALITY GATE THRESHOLDS
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class QualityThresholds:
    # CI thresholds
    min_unit_test_coverage: float = 90.0
    max_lint_errors: int = 0
    max_type_errors: int = 0
    max_critical_vulnerabilities: int = 0
    max_high_vulnerabilities: int = 0
    max_p99_latency_ms: int = 200
    max_docker_image_size_mb: int = 500

    # CD thresholds
    max_canary_error_rate_pct: float = 1.0
    max_canary_p99_latency_ms: int = 500
    canary_traffic_pct: int = 5
    progressive_rollout_steps: List[int] = field(
        default_factory=lambda: [5, 25, 50, 100]
    )
    progressive_step_wait_minutes: int = 5
    post_deploy_alert_window_minutes: int = 30

    # SBOM / supply chain
    require_sbom: bool = True
    require_container_signing: bool = True


QUALITY_THRESHOLDS = QualityThresholds()


# --------------------------------------------------------------------------- #
# SDK RELEASE CONFIG
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SDKReleaseTarget:
    platform: str
    package_name: str
    registry: str
    build_tool: str
    validation: str


SDK_RELEASE_TARGETS = [
    SDKReleaseTarget(
        "web", "@aether/sdk",
        "npm + CDN (cdn.aether.network)", "esbuild",
        "Semantic versioning, automatic changelog",
    ),
    SDKReleaseTarget(
        "ios", "AetherSDK",
        "CocoaPods + Swift Package Manager", "xcodebuild",
        "Xcode Cloud build, TestFlight validation",
    ),
    SDKReleaseTarget(
        "android", "com.aether:aether-android",
        "Maven Central", "gradle",
        "Gradle build, Firebase Test Lab",
    ),
    SDKReleaseTarget(
        "react_native", "@aether/react-native",
        "npm", "metro",
        "Coordinated native dependency updates",
    ),
]


# --------------------------------------------------------------------------- #
# TERRAFORM / IaC CONFIG
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class TerraformConfig:
    state_backend: str = "s3"
    state_bucket: str = "aether-terraform-state"
    lock_table: str = "aether-terraform-locks"
    plan_review_tool: str = "atlantis"
    drift_detection_cron: str = "0 6 * * *"
    modules: List[str] = field(default_factory=lambda: [
        "vpc", "ecs", "rds", "elasticache", "neptune",
        "s3", "cloudfront", "sagemaker", "iam", "monitoring",
    ])


TERRAFORM_CONFIG = TerraformConfig()


# --------------------------------------------------------------------------- #
# NOTIFICATION CONFIG  (NEW)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class NotificationConfig:
    """Centralised notification settings for all pipeline events."""
    slack_channel_ci: str = "#aether-ci"
    slack_channel_cd: str = "#aether-deploys"
    slack_channel_demo: str = "#aether-demo"
    slack_channel_alerts: str = "#aether-alerts"
    slack_webhook_env_var: str = "SLACK_WEBHOOK"
    pagerduty_routing_key_env_var: str = "PAGERDUTY_ROUTING_KEY"
    notify_on_ci_failure: bool = True
    notify_on_cd_start: bool = True
    notify_on_cd_success: bool = True
    notify_on_rollback: bool = True
    notify_on_drift: bool = True


NOTIFICATION_CONFIG = NotificationConfig()


# --------------------------------------------------------------------------- #
# CACHE / ARTIFACT CONFIG  (NEW)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CacheConfig:
    """Artifact and dependency caching settings."""
    turbo_remote_cache: bool = True
    docker_layer_cache: bool = True
    pip_cache_dir: str = "~/.cache/pip"
    npm_cache_dir: str = "~/.npm"
    ecr_lifecycle_keep_count: int = 25
    ecr_lifecycle_untagged_days: int = 7


CACHE_CONFIG = CacheConfig()


# --------------------------------------------------------------------------- #
# CHANGE DETECTION CONFIG  (NEW)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ChangeDetectionConfig:
    """Monorepo change detection for selective CI/CD runs."""
    enabled: bool = True
    base_ref: str = "origin/develop"
    # Paths that trigger full pipeline (no skipping)
    always_run_paths: List[str] = field(default_factory=lambda: [
        ".github/",
        "config/",
        "deploy/aws/",
        "packages/shared/",
    ])
    # Map from path prefix to affected service names
    service_path_map: Dict[str, str] = field(default_factory=lambda: {
        "services/ingestion":    "ingestion",
        "services/backend/services/identity":     "identity",
        "services/backend/services/analytics":    "analytics",
        "services/backend/services/ml_serving":   "ml-serving",
        "services/backend/services/agent":        "agent",
        "services/backend/services/campaign":     "campaign",
        "services/backend/services/consent":      "consent",
        "services/notification": "notification",
        "services/admin":        "admin",
    })


CHANGE_DETECTION_CONFIG = ChangeDetectionConfig()
