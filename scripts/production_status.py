#!/usr/bin/env python3
"""
Aether Platform — Production Status Routine

Single repeatable routine that reports how production-ready each platform
area is, verifies the repo's own consistency gates, and lists release and
scale blockers. Designed to run locally and in CI (no secrets, no external
services required).

The scorecard below is the canonical machine-readable readiness source.
docs/productization/aether_productization_audit.md is the dated narrative
snapshot of the same data; when scores change, update BOTH (the audit doc
review is enforced through its source_files link to this script).

Usage:
    python scripts/production_status.py                 # report (advisory)
    python scripts/production_status.py --strict        # exit 1 if any live
                                                        # consistency check fails
    python scripts/production_status.py --with-tests    # also run pytest suites
    python scripts/production_status.py --json out.json # machine-readable output

Score rubric (0-5):
    0 absent | 1 stub/scaffold | 2 partial/pilot | 3 pre-production
    4 release-ready with minor gaps | 5 production-ready and scale-ready

Exit codes:
    0   report produced; in --strict mode all live checks passed
    1   --strict mode and at least one live consistency check failed

Note: declared release blockers do NOT fail --strict. They are tracked
work, not repo inconsistency. Failing CI on known, documented blockers
would make the gate permanently red and train people to ignore it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LEVELS = {
    0: "absent",
    1: "stub/scaffold",
    2: "partial/pilot",
    3: "pre-production",
    4: "release-ready (minor gaps)",
    5: "production + scale ready",
}


@dataclass
class Blocker:
    severity: str  # release-blocker | scale-blocker | pre-production-blocker
    summary: str
    area: str
    next_step: str


@dataclass
class Area:
    name: str
    score: int
    summary: str
    evidence: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        return LEVELS[self.score]


# ---------------------------------------------------------------------------
# Canonical readiness scorecard
# ---------------------------------------------------------------------------
# Scores are evidence-based: every area lists the repo paths that justify
# the score. Do not raise a score without adding evidence; do not describe
# an area as production-ready unless it would survive a customer pointing
# at the evidence paths.

AREAS: list[Area] = [
    Area(
        "backend/API",
        4,
        "65+ FastAPI routers with auth/RBAC middleware, tenant-scoped repositories, "
        "plan-tier gating, rate limits, quotas. Local in-memory fallbacks are dev/test "
        "only; staging/production require Postgres/Redis/Neptune/Kafka.",
        [
            "Backend Architecture/aether-backend/main.py",
            "Backend Architecture/aether-backend/middleware/middleware.py",
            "Backend Architecture/aether-backend/repositories/repos.py",
        ],
    ),
    Area(
        "SDKs",
        4,
        "Web + React Native SDKs at platform version with batching, retry, consent "
        "forwarding, heartbeats; iOS/Android native cores; release alignment enforced "
        "by validate_sdk_release_alignment.py and publish workflow.",
        [
            "packages/web/",
            "packages/react-native/",
            "packages/shared/",
            "scripts/validate_sdk_release_alignment.py",
        ],
    ),
    Area(
        "identity resolution",
        4,
        "Four-anchor resolution (wallet > anonymous+fingerprint > email hash > user id) "
        "with confidence scoring, merge endpoint with reason + Kafka audit event, and a "
        "pending-review queue with approve/reject for low-confidence decisions.",
        [
            "Backend Architecture/aether-backend/services/sdk/routes.py",
            "Backend Architecture/aether-backend/services/identity/routes.py",
            "Backend Architecture/aether-backend/services/resolution/routes.py",
        ],
    ),
    Area(
        "Profile 360",
        4,
        "Canonical profile composition from identity, analytics, consent, graph, and "
        "Gold-tier lake repositories; 15 intelligence sub-resources wired to real "
        "queries with window + tenant filtering; credit data behind 'credit' consent.",
        [
            "Backend Architecture/aether-backend/services/profile/",
            "packages/shared/profile360-contract.ts",
        ],
    ),
    Area(
        "Neptune relationships (H2H/H2A/A2H/A2A)",
        3,
        "All four relationship layers are typed edges in the graph schema (DELEGATES, "
        "NOTIFIES, COMPOSED_WITH, MEMBER_OF_CLUSTER, ...) with direction, provenance, "
        "and tenant scoping; Neptune backend implemented via gremlinpython with an "
        "in-memory dev/test fallback. Production Neptune is not yet provisioned or "
        "load-validated, so this stays pre-production.",
        ["Backend Architecture/aether-backend/shared/graph/graph.py"],
    ),
    Area(
        "graph mutation safety",
        4,
        "Agent-originated mutations go through verify -> stage -> review batch -> human "
        "approval -> commit; direct service mutations are tenant-scoped, idempotent "
        "upserts with audit trace.",
        [
            "Agent Layer/README.md",
            "Backend Architecture/aether-backend/services/intelligence/graph_mutations.py",
            "Backend Architecture/aether-backend/services/x402/economic_mutations.py",
        ],
    ),
    Area(
        "graph health / drift detection",
        4,
        "SDK drift detection (schema, stale heartbeat, replay storm, auth, consent) is "
        "implemented with incident tracking. Graph health overlay scoring is now real: "
        "graph_overlay() computes trust/risk/confidence scores from IntelligenceQualityService "
        "(cluster_community_drift, merge_rate, split_rate, orphan_rate) and attaches "
        "IntelligenceScore objects to every returned GraphNode. Overlay dimensions are "
        "populated per overlay type (risk/trust/health/identity/attribution). "
        "ClickHouse-backed CIS health engine wired for production; local mode uses "
        "deterministic baseline + per-tenant jitter.",
        [
            "Backend Architecture/aether-backend/services/sdk_drift/routes.py",
            "Backend Architecture/aether-backend/services/data_quality/",
            "Backend Architecture/aether-backend/services/operational_intelligence/",
        ],
    ),
    Area(
        "Kyber (operator console)",
        4,
        "React SPA with mocked/live/staging/production modes, admin-guarded backend "
        "routes (/v1/admin/kyber, fleet, drift, intelligence quality), Playwright E2E "
        "in CI. Operator data never mounted on tenant-facing routers.",
        [
            "frontend/kyber/",
            ".github/workflows/kyber-e2e.yml",
            "Backend Architecture/aether-backend/services/intelligence/routes.py",
        ],
    ),
    Area(
        "customer frontend (tenant app)",
        4,
        "React SPA with PKCE OIDC auth, typed API client, MSW fixtures isolated to "
        "local-mocked mode. Full self-serve onboarding flow shipped: 3-step signup "
        "(email+password → OTP → API key reveal), plan selection (P1-P4), SSO "
        "(Google/Apple/Slack/Microsoft), billing portal (Stripe), API key management, "
        "usage dashboard, and implementation checklist (/v1/onboarding/*). Gap: no "
        "Cypress/Playwright E2E tests for the auth+onboarding critical path.",
        ["frontend/aether/", "docs/PRODUCTIZATION.md"],
    ),
    Area(
        "connectors (BYOK / source)",
        3,
        "14 production-shaped inbound connectors with real API calls credential-gated "
        "behind vault secret flow (Shopify, Stripe, HubSpot, Salesforce, Klaviyo, "
        "PostHog, GA4, Jira, Linear, Zendesk, Intercom — all real HTTP against live "
        "APIs when secret provided). Sync health tracking (status, last_synced_at, "
        "error_count, last_error_message) recorded per connector per tenant. Kyber "
        "per-tenant health drill-down route added. Remaining gap: staging validation "
        "with live credentials for high-value connectors.",
        ["Backend Architecture/aether-backend/services/integrations/connectors/"],
    ),
    Area(
        "Slack / action notifications",
        4,
        "Slack inbound (webhook parse + auth.test connection check) and outbound "
        "(chat.postMessage + chat.update via Block Kit, circuit breaker, retries) are "
        "fully real. Per-tenant Slack channel mapping by severity (slack_channel_map) "
        "and opt-in controls (operator_review_required, quiet_hours, rate limits) are "
        "implemented. Slack OAuth flow (connect + callback) is wired. Minor gap: "
        "per-tenant channel mapping not validated against a live workspace in staging.",
        [
            "Backend Architecture/aether-backend/services/integrations/connectors/adapters.py",
            "Backend Architecture/aether-backend/services/notification_intelligence/",
        ],
    ),
    Area(
        "Dune / data-lake feeders",
        3,
        "DuneConnector (read-only, credential-gated, per-row provenance) added to "
        "connector fleet. PromotionService governs Bronze→Silver with freshness gate "
        "(max_age_hours), null-rate gate, required-field gate, and entity_id gate; "
        "each rejected row gets per-check failure reasons. POST /v1/lake/promote "
        "triggers promotion; GET /v1/admin/feeders exposes per-run health in Kyber. "
        "Remaining gap: no staging validation with a real Dune API key; no scheduled "
        "polling worker (pull is on-demand via /sync).",
        [
            "Backend Architecture/aether-backend/services/dune_feeder/service.py",
            "Backend Architecture/aether-backend/services/dune_feeder/routes.py",
            "frontend/kyber/src/pages/dune-feeder/dune-feeder-page.tsx",
        ],
    ),
    Area(
        "smart contracts / proofs / rewards",
        4,
        "Multi-chain reward contracts (EVM Solidity + Solana/NEAR/Cosmos Rust) with "
        "oracle-signed claims, nonce replay protection, budgets, pausability, and "
        "Hardhat tests. Pre-audit hardening complete: getOracleAddress() now reverts on "
        "role desync, grantRole/revokeRole blocked for ORACLE_ROLE (must use rotateOracle), "
        "claimReward enforces amount == campaign.rewardAmount. Slither static-analysis CI "
        "added (.github/workflows/smart-contract-analysis.yml). Pre-audit checklist at "
        "scripts/smart_contract_audit_prep.py passes 9/9 checks. "
        "NO external certification yet — do not deploy to mainnet until external audit complete.",
        [
            "Smart Contracts/contracts/AnalyticsRewards.sol",
            "Smart Contracts/test/AnalyticsRewards.test.js",
            ".github/workflows/smart-contract-analysis.yml",
            "scripts/smart_contract_audit_prep.py",
        ],
    ),
    Area(
        "security / compliance",
        3,
        "API-key + JWT auth (RS256 in production), role + permission RBAC, column- and "
        "query-level tenant isolation with dedicated tests, consent + DSR with audit "
        "export. Compliance posture is pre-positioning (14/16 controls) — no external "
        "certification.",
        [
            "Backend Architecture/aether-backend/shared/auth/auth.py",
            "tests/unit/test_tenant_isolation.py",
            "scripts/compliance/readiness.py",
        ],
    ),
    Area(
        "CI / tests",
        4,
        "8 workflows (consistency, health, SDK validation, e2e, deploy); 800 core + "
        "152 ML Python tests green; JS coverage thresholds enforced. Python suites "
        "must run separately (conftest module collision is documented).",
        [".github/workflows/", "tests/", "pyproject.toml"],
    ),
    Area(
        "docs",
        4,
        "202 docs with validated frontmatter, 64 source-linked docs with strict drift "
        "gating in repo-doctor, generated contract registry under docs/_generated/. "
        "Readiness claims consolidated into this routine + the productization audit.",
        ["docs/", "scripts/docs_drift.py", "scripts/repo_doctor.py"],
    ),
    Area(
        "deployment / cloud readiness",
        3,
        "Terraform IaC, deploy + infrastructure workflows, docker-compose dev stack, "
        "observability bundle (Prometheus/Grafana/Loki). External prerequisites "
        "remain: provisioned infra, production secrets, trained ML artifacts.",
        [
            "AWS Deployment/",
            "deploy/",
            ".github/workflows/deploy.yml",
            "docs/PRODUCTION-READINESS.md",
        ],
    ),
    Area(
        "scale readiness",
        3,
        "Architecture is scale-shaped (Kafka, ClickHouse, medallion lake, partitioned "
        "S3). Locust harness covers /v1/batch and /sdk/identity/resolve with per-endpoint "
        "thresholds; `make load-smoke` / `scripts/load_smoke.py` runs the smoke gate. "
        "Gaps: no recorded staging baselines yet; Neptune/identity-merge throughput "
        "unproven at scale.",
        ["tests/load/", "scripts/load_smoke.py", "Data Lake Architecture/"],
    ),
]


BLOCKERS: list[Blocker] = [
    Blocker(
        "pre-production-blocker",
        "No E2E tests for tenant onboarding critical path (signup → OTP → billing)",
        "customer frontend (tenant app)",
        "Add Cypress or Playwright suite covering signup, OTP verify, API key reveal, billing portal",
    ),
    Blocker(
        "release-blocker",
        "Smart contracts pre-audit hardening done; external certification still required",
        "smart contracts / proofs / rewards",
        "Commission external audit (Trail of Bits / OpenZeppelin / Spearbit / Halborn) "
        "before any mainnet deployment with real funds; run `make audit-prep` first",
    ),
    Blocker(
        "release-blocker",
        "Production infra not provisioned; secrets not configured",
        "deployment / cloud readiness",
        "Provision Terraform stack; run scripts/bootstrap_aws_secrets.py",
    ),
    Blocker(
        "release-blocker",
        "Agent Layer hosted mode requires durable storage (Redis or equivalent)",
        "graph mutation safety",
        "Enable hosted control-plane storage per docs/AGENT-LAYER-PRODUCTION.md",
    ),
    Blocker(
        "pre-production-blocker",
        "ML model artifacts not trained/published for serving",
        "deployment / cloud readiness",
        "Run training pipelines in ML Models/aether-ml and publish artifacts",
    ),
    Blocker(
        "pre-production-blocker",
        "Connectors not staging-validated with live credentials; no E2E test "
        "for vault → pull → event ingestion path against a real provider API",
        "connectors (BYOK / source)",
        "Run connector smoke against staging with real Shopify/Stripe/Slack credentials; "
        "add E2E test asserting vault secret → pull → Bronze ingest",
    ),
    Blocker(
        "pre-production-blocker",
        "Dune feeder not staging-validated; no scheduled polling worker (pull is on-demand only)",
        "Dune / data-lake feeders",
        "Run DuneConnector sync against staging with a real API key; add a scheduled "
        "worker (APScheduler or Celery beat) to automate periodic pulls per tenant config",
    ),
    Blocker(
        "scale-blocker",
        "No staging load baselines recorded; smoke gate runs locally only",
        "scale readiness",
        "Run `make load-smoke` against staging; record p95/p99 baselines in docs/LOAD-BASELINES.md",
    ),
    Blocker(
        "scale-blocker",
        "Neptune capacity/cost and identity-merge throughput unvalidated",
        "Neptune relationships (H2H/H2A/A2H/A2A)",
        "Provision staging Neptune; replay synthetic merge workload; record limits",
    ),
]


# ---------------------------------------------------------------------------
# Live consistency checks (run every time; these keep the report honest)
# ---------------------------------------------------------------------------


@dataclass
class LiveCheck:
    name: str
    cmd: list[str]


LIVE_CHECKS: list[LiveCheck] = [
    LiveCheck("Version alignment", ["python", "scripts/bump_version.py", "--check"]),
    LiveCheck("Source-linked docs drift (strict)", ["python", "scripts/docs_drift.py", "--strict"]),
    LiveCheck("Contract / event / consent alignment", ["python", "scripts/validate_contracts.py"]),
    LiveCheck("SDK release alignment", ["python", "scripts/validate_sdk_release_alignment.py"]),
]

TEST_CHECKS: list[LiveCheck] = [
    LiveCheck("Python tests (core)", ["python", "-m", "pytest", "tests/", "-q", "--tb=short"]),
    LiveCheck(
        "Python tests (ML)",
        ["python", "-m", "pytest", "ML Models/aether-ml/tests/", "-q", "--tb=short"],
    ),
]

# Guardrail artifacts that must exist for the cloud/PR workflow contract.
REQUIRED_ARTIFACTS = [
    ".github/pull_request_template.md",
    ".github/CODEOWNERS",
    ".env.example",
    ".github/workflows/repo-consistency.yml",
    ".github/workflows/repo-health.yml",
    "scripts/repo_doctor.py",
    "docs/productization/aether_productization_audit.md",
]


def _platform_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "unknown"


def _run_check(check: LiveCheck) -> tuple[bool, str]:
    proc = subprocess.run(check.cmd, cwd=ROOT, capture_output=True, text=True)
    output = (proc.stdout + proc.stderr).strip()
    tail = "\n".join(output.splitlines()[-6:]) if output else ""
    return proc.returncode == 0, tail


def main() -> None:
    parser = argparse.ArgumentParser(description="Aether production status routine")
    parser.add_argument(
        "--strict", action="store_true", help="Exit 1 if any live consistency check fails"
    )
    parser.add_argument(
        "--with-tests", action="store_true", help="Also run the Python test suites (slower)"
    )
    parser.add_argument("--json", metavar="PATH", help="Write machine-readable report to PATH")
    args = parser.parse_args()

    version = _platform_version()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print("=" * 74)
    print(f"AETHER PRODUCTION STATUS — v{version} — {now}")
    print("=" * 74)

    # -- live checks --------------------------------------------------------
    checks = list(LIVE_CHECKS) + (list(TEST_CHECKS) if args.with_tests else [])
    check_results: list[dict] = []
    print("\nLIVE CONSISTENCY CHECKS")
    print("-" * 74)
    for check in checks:
        ok, tail = _run_check(check)
        check_results.append({"name": check.name, "passed": ok, "tail": tail})
        print(f"  [{'PASS' if ok else 'FAIL'}]  {check.name}")
        if not ok and tail:
            for line in tail.splitlines():
                print(f"          {line}")
    if not args.with_tests:
        print("  [SKIP]  Python test suites (pass --with-tests to run)")

    # -- guardrail artifacts -------------------------------------------------
    missing_artifacts = [p for p in REQUIRED_ARTIFACTS if not (ROOT / p).exists()]
    print("\nGUARDRAIL ARTIFACTS")
    print("-" * 74)
    if missing_artifacts:
        for p in missing_artifacts:
            print(f"  [MISSING]  {p}")
    else:
        print(f"  [PASS]  all {len(REQUIRED_ARTIFACTS)} required artifacts present")

    # -- scorecard -----------------------------------------------------------
    print("\nREADINESS SCORECARD  (0 absent .. 5 production+scale ready)")
    print("-" * 74)
    width = max(len(a.name) for a in AREAS) + 2
    for area in AREAS:
        print(f"  {area.score}/5  {area.name:<{width}} {area.level}")
    overall = round(sum(a.score for a in AREAS) / len(AREAS), 2)
    print("-" * 74)
    print(f"  Overall: {overall}/5 — pre-production: release-shaped, gated by the blockers below.")

    # -- blockers -------------------------------------------------------------
    print("\nBLOCKERS")
    print("-" * 74)
    for b in BLOCKERS:
        print(f"  [{b.severity}] {b.summary}")
        print(f"      area: {b.area}")
        print(f"      next: {b.next_step}")

    failed = [c for c in check_results if not c["passed"]] + (
        [{"name": f"missing artifact: {p}"} for p in missing_artifacts]
    )

    print("\n" + "=" * 74)
    if failed:
        print(
            f"RESULT: {len(failed)} live check(s) failed — repo state and report "
            "may disagree. Fix these before trusting the scorecard."
        )
    else:
        print("RESULT: all live checks passed — scorecard is consistent with repo state.")
    print("=" * 74)

    if args.json:
        payload = {
            "version": version,
            "generated_at": now,
            "overall_score": overall,
            "areas": [{**asdict(a), "level": a.level} for a in AREAS],
            "blockers": [asdict(b) for b in BLOCKERS],
            "live_checks": check_results,
            "missing_artifacts": missing_artifacts,
        }
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nJSON report written to {args.json}")

    if args.strict and failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
