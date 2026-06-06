---
title: CI/CD Pipeline — Stages, Gates & SDK Release
slug: operations/cicd
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "8.8.0"
source_files:
  - cicd/aether-cicd/README.md
  - cicd/aether-cicd/main.py
  - cicd/aether-cicd/stages/
  - cicd/aether-cicd/quality_gates/
  - .github/workflows/
canonical_owner: platform@aether
estimated_read_minutes: 12
toc_depth: 3
last_synced_commit: 306de9c1f6e47a3aeda6fc3302d7778c98417666
---

# CI/CD Pipeline — Stages, Gates & SDK Release

Internal reference for Aether's automated delivery pipeline. The CI/CD system is
a Python orchestrator (`cicd/aether-cicd/`) that wraps GitHub Actions workflows
and enforces quality gates before any artefact reaches a deployment target.

## Branch strategy

Aether uses GitFlow with six permanent branch types:

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code; only receives merges from `release/*` and `hotfix/*` |
| `staging` | Pre-production integration; receives from `develop` for staging deploys |
| `develop` | Integration branch for feature work |
| `demo` | Stable demo environment; fed from `staging` on explicit promote |
| `feature/*` | Short-lived feature branches off `develop` |
| `hotfix/*` | Emergency patches off `main`; merged back to both `main` and `develop` |
| `release/*` | Release preparation off `develop`; merged to `main` and `develop` on ship |

## AWS accounts

The pipeline operates across six isolated AWS accounts:

| Account | ID | Purpose |
|---------|-----|---------|
| dev | `111111111111` | Developer sandbox; auto-deployed from `develop` |
| staging | `222222222222` | Pre-prod integration; auto-deployed from `staging` |
| production | `333333333333` | Customer traffic; canary-gated deploys from `main` |
| data | `444444444444` | Data plane (ClickHouse, S3, MSK, SageMaker) |
| security | `555555555555` | Security tooling and audit log aggregation |
| demo | `666666666666` | Demo environment; deployed from `demo` branch |

## CI stages

Each pull request runs eight sequential stages. A failure at any stage stops the
pipeline and blocks the merge.

### 1. Lint / static checks

- `python -m ruff check .` for Python correctness-oriented linting.
- `npm run lint` for TypeScript workspace static checks. The workspace lint scripts intentionally run TypeScript compiler validation so CI does not depend on an unpinned ESLint parser/config package.
- Gate: **0 errors**.

### 2. Type check

- `npm run typecheck` across the TypeScript SDK/operator workspaces.
- Python runtime syntax is validated with `compileall` for the backend, agent layer, and security package.
- Gate: **0 type/syntax errors**.

### 3. Unit tests

- Vitest via `npm test` for TypeScript SDKs and frontends.
- Pytest via `python -m pytest tests/ -n auto --tb=short` for core Python tests; ML tests run when `ML Models/**` changes.
- Gate: **all tests pass**.

### 4. Integration tests

- Spins up ephemeral Docker Compose stack (Postgres, Redis, Kafka, ClickHouse)
- Runs service-to-service integration suites
- Gate: **all tests green**

### 5. Security scan

- Trivy container vulnerability scan on every built image
- `npm audit --audit-level=critical` on Node packages
- `pip-audit` on Python packages
- Semgrep SAST on application code
- Gate: **0 critical vulnerabilities**

### 6. Build

- Docker images built and pushed to ECR (tagged with the commit SHA)
- TypeScript packages compiled; `packages/web/dist/` populated
- SDK artefacts staged for release (see SDK Release below)
- Gate: **all builds succeed, images < 500 MB compressed**

### 7. E2E tests

- Playwright test suite against a freshly deployed ephemeral environment
- Covers critical user journeys: sign-up, wallet connect, event ingestion, dashboard
- Gate: **all E2E tests green**

### 8. Performance tests

- k6 load test against the ingestion endpoint (1 000 RPS for 60 s)
- Gate: **P99 latency < 200 ms, error rate < 0.1%**

## CD stages

Merges to `main` (from `release/*` or `hotfix/*`) trigger the CD pipeline.

### 1. Staging deploy

ECS service update rolled out to the `staging` account using the commit-SHA image.
Terraform plan is applied for any infrastructure changes.

### 2. Staging smoke tests

Automated smoke suite hits staging endpoints. Gate: all checks green.

### 3. Canary deploy (5%)

5% of production traffic shifted to the new task revision in the `production`
account. Alarm monitoring begins.

### 4. Canary validation (15 min)

Automated hold: CloudWatch alarms for error rate, latency, and memory are
evaluated every 60 seconds for 15 minutes. Any alarm breach triggers automatic
rollback.

### 5. Progressive rollout

Traffic shifted in stages: 5% → 25% → 50% → 100%. Each step holds for 5 minutes
with the same alarm guard. Automatic rollback on breach at any step.

### 6. Post-deploy

- Cache warm-up tasks run against production
- PagerDuty alert suppression window closed
- Deployment record written to the audit log
- Slack notification sent to `#deploys`

## Quality gates reference

| Gate | Threshold | Stage |
|------|-----------|-------|
| Line coverage | ≥ 90% | Unit tests |
| Lint errors | 0 | Lint |
| Type errors | 0 | Type check |
| Critical CVEs | 0 | Security scan |
| E2E pass rate | 100% | E2E tests |
| P99 latency | < 200 ms | Performance |
| Error rate | < 0.1% | Performance / Canary |
| Image size | < 500 MB | Build |

Thresholds are enforced in `cicd/aether-cicd/quality_gates/`. Editing them
requires a separate review from `platform@aether`.

## SDK release

When a `release/*` branch is merged to `main`, the SDK release sub-pipeline fires
alongside the service deploy:

| Platform | Registry | Trigger |
|----------|----------|---------|
| Web (`packages/web`) | npm (`@aether/web`) | Version bump in `package.json` |
| iOS (`packages/ios`) | CocoaPods (`AetherSDK`) | Version bump in `AetherSDK.podspec` |
| Android (`packages/android`) | Maven Central (`network.aether:sdk`) | Version bump in `build.gradle` |
| React Native (`packages/react-native`) | npm (`@aether/react-native`) | Version bump in `package.json` |

The release script (`cicd/aether-cicd/scripts/release_sdk.py`) validates that the
version in the manifest matches the git tag before publishing.

## Hotfix procedure

1. Branch off `main`: `git checkout -b hotfix/description main`
2. Apply the fix and increment the patch version.
3. Open a PR targeting `main`. CI runs the full 8-stage suite.
4. On merge, the CD pipeline executes the full canary rollout.
5. Immediately after merge to `main`, open a second PR to merge the hotfix into
   `develop` to keep branches in sync.

## Adding a new CI stage

1. Add a stage class in `cicd/aether-cicd/stages/` implementing the `Stage`
   protocol.
2. Register it in `cicd/aether-cicd/main.py`'s `STAGES` list at the correct
   position.
3. Add a matching quality gate in `cicd/aether-cicd/quality_gates/` if it
   produces a measurable threshold.
4. Update the GitHub Actions workflow (`.github/workflows/ci.yml`) to invoke the
   new stage.
5. Document the gate threshold in this page.
