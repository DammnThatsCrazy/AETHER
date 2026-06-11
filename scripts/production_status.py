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
        "implemented with incident tracking. Graph overlay endpoint now returns real "
        "data-quality scores (graph_quality_score, open drift/contamination counts) via "
        "intelligence_quality_service. Overlay dimensions are wired to contamination, "
        "identity, trust, risk, attribution, agent, and wallet scoring. Remaining gap: "
        "Neptune-backed live graph health scoring (Neptune not yet provisioned in staging).",
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
        "in CI. Operator data never mounted on tenant-facing routers. Shared operator "
        "contracts (operator-scope, graph-health, kyber-command) published to "
        "packages/shared; Dune feeder health exposed via /v1/admin/dune-feeder/health.",
        [
            "frontend/kyber/",
            ".github/workflows/kyber-e2e.yml",
            "Backend Architecture/aether-backend/services/intelligence/routes.py",
            "packages/shared/operator-scope.ts",
            "packages/shared/graph-health.ts",
            "packages/shared/kyber-command.ts",
        ],
    ),
    Area(
        "customer frontend (tenant app)",
        4,
        "React SPA with PKCE OIDC auth, typed API client, MSW fixtures isolated to "
        "local-mocked mode. Self-serve signup flow implemented: email registration → "
        "6-digit OTP verify → tenant creation + API key reveal → SDK install guide "
        "(Web, iOS, Android, React Native). SSO providers wired. Login page wired "
        "against /v1/auth/login.",
        [
            "frontend/aether/src/pages/signup/signup-page.tsx",
            "Backend Architecture/aether-backend/services/auth/routes.py",
            "frontend/aether/src/app/router.tsx",
        ],
    ),
    Area(
        "connectors (BYOK / source)",
        3,
        "Connector framework (descriptor, vault-backed secrets, sync status, webhook "
        "parse, normalization) is production-shaped. 9 of 14 adapters (Shopify, "
        "HubSpot, Salesforce, Klaviyo, PostHog, GA4, Jira, Zendesk, Intercom) have "
        "real HTTP pull() implementations behind credential gates. Slack live "
        "auth.test wired. Mocked-HTTP tests cover pull() and test_connection() for "
        "all wired adapters, proving real adapter logic without external calls. "
        "Connector health rollup and Kyber tenant panel are exposed. Remaining gap: "
        "real production secrets required for staging validation.",
        [
            "Backend Architecture/aether-backend/services/integrations/connectors/",
            "tests/unit/test_connector_pulls.py",
        ],
    ),
    Area(
        "Slack / action notifications",
        3,
        "Slack is correctly modeled as an action/messaging connector (auth.test "
        "connection check, webhook parse, tenant-scoped secrets) and notification "
        "routing exists; outbound channel mapping and per-tenant opt-in templates are "
        "not yet productized.",
        [
            "Backend Architecture/aether-backend/services/integrations/connectors/adapters.py",
            "Backend Architecture/aether-backend/services/notification_intelligence/",
        ],
    ),
    Area(
        "Dune / data-lake feeders",
        4,
        "Governed DuneFeederService implemented: Dune query results ingest to Bronze "
        "with per-row SHA-256 hash, provenance chain, freshness gate (configurable "
        "max_age_seconds), and quality gate (schema + required-field validation). "
        "Silver promotion is an explicit operator action (/v1/admin/dune-feeder/promote). "
        "Gold materialization implemented: /v1/admin/dune-feeder/materialize-gold aggregates "
        "Silver rows by (domain, query_id) into curated Gold records with idempotency guard. "
        "Rollback by source_tag removes Bronze + Silver + Gold. Graph isolation invariant "
        "enforced and tested (32 unit tests). Remaining gap: staging validation with live "
        "Dune credentials; Gold tier backed by in-memory store pending persistent lake backend.",
        [
            "Backend Architecture/aether-backend/services/dune_feeder/",
            "Backend Architecture/aether-backend/shared/providers/categories.py",
            "tests/unit/test_dune_feeder.py",
        ],
    ),
    Area(
        "smart contracts / proofs / rewards",
        3,
        "Multi-chain reward contracts (EVM Solidity + Solana/NEAR/Cosmos Rust) with "
        "oracle-signed claims, nonce replay protection, budgets, pausability, and "
        "Hardhat tests. NO external security audit has been performed — do not deploy "
        "to mainnet with real funds until one is.",
        [
            "Smart Contracts/contracts/AnalyticsRewards.sol",
            "Smart Contracts/test/AnalyticsRewards.test.js",
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
        "S3). Locust harness extended with /v1/ingest/batch, /v1/resolution/resolve, "
        "Profile360, Kyber summary, and GraphQL scenarios. Synthetic in-memory "
        "baselines recorded (tests/load/baseline_results.json) — all p95 latencies "
        "within documented thresholds. Staging thresholds defined in "
        "tests/load/thresholds.json. Remaining scale gap: real staging baselines on "
        "provisioned infra; Neptune/identity-merge throughput unvalidated.",
        [
            "tests/load/locustfile.py",
            "tests/load/synthetic_baseline.py",
            "tests/load/thresholds.json",
            "tests/load/baseline_results.json",
            "Data Lake Architecture/",
        ],
    ),
]


BLOCKERS: list[Blocker] = [
    Blocker(
        "release-blocker",
        "Smart contracts have no external security audit",
        "smart contracts / proofs / rewards",
        "Commission external audit before any mainnet deployment with real funds",
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
        "Connector staging validation requires real provider secrets",
        "connectors (BYOK / source)",
        "Provision staging secrets vault; run test_connection() + pull() against real providers",
    ),
    Blocker(
        "pre-production-blocker",
        "Dune feeder staging validation requires live Dune credentials; in-memory store only",
        "Dune / data-lake feeders",
        "Provision staging secrets vault with Dune API key; run feeder against live Dune API; implement persistent lake backend",
    ),
    Blocker(
        "scale-blocker",
        "Synthetic load baselines recorded; real staging load baselines still pending",
        "scale readiness",
        "Provision staging infra; run locustfile.py against staging; record p95/p99 and compare to thresholds.json",
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
