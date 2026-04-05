# 06 — CI/CD Pipeline

Complete CI/CD spec for v-Next build, with security gates, artifact signing, and rollback procedures.

---

## Pipeline stages

```
┌──────────────┐
│ Pre-commit   │  lint, format, gitleaks, type check, docs-exist
└──────┬───────┘
       ▼
┌──────────────┐
│ PR Open      │  unit, integration, contract, preservation,
│              │  SBOM generation, dep scan, SAST
└──────┬───────┘
       ▼
┌──────────────┐
│ PR Ready     │  e2e smoke, load test (single endpoint),
│              │  model card check (if ML PR)
└──────┬───────┘
       ▼
┌──────────────┐
│ Security Lbl │  adversarial suite, secret rotation check,
│              │  ZK circuit validation (if applicable)
└──────┬───────┘
       ▼
┌──────────────┐
│ Integration  │  full suite + load + preservation regression
│ branch merge │
└──────┬───────┘
       ▼
┌──────────────┐
│ Main merge   │  cosign sign, SBOM attach, MLflow promote,
│              │  staging deploy, smoke
└──────┬───────┘
       ▼
┌──────────────┐
│ Production   │  canary deploy, observability gate,
│              │  feature flag ramp
└──────────────┘
```

---

## Pre-commit hooks

Location: `.pre-commit-config.yaml` (extend existing)

Add to existing hooks:

| Hook | Purpose |
|---|---|
| `ruff` / `black` | Python formatting |
| `prettier` | TypeScript formatting |
| `eslint` | TypeScript linting |
| `mypy` | Python type check |
| `gitleaks` | Secret detection |
| `trufflehog` | Additional secret scanning |
| `bandit` | Python security lint |
| `migration-lint` | Block destructive migrations |
| `openapi-diff` | Detect v1 API breaking changes |

---

## GitHub Actions workflows

New workflows to add:

### `.github/workflows/vnext-ci.yml`
```
# Runs on PR to claude/explore-ml-improvements-Mr3Kz
# Tests: unit + integration + contract + preservation
# Coverage gate: ≥85% new code
# Blocks merge on any failure
```

### `.github/workflows/vnext-security.yml`
```
# Runs on: push to any vnext branch, nightly, security label
# Tests: adversarial suite + SAST + secret scan
# Generates: SBOM + signs with cosign
# Uploads to artifact registry
```

### `.github/workflows/vnext-preservation.yml`
```
# Runs on every PR (required)
# Tests: all /v1 endpoint snapshots + existing graph types +
#        existing MLflow models + agent controller workflow +
#        staged mutation flow + ingestion pipeline + Shiki routes
# BLOCKS MERGE on any preservation failure
```

### `.github/workflows/vnext-ml.yml`
```
# Runs on ML PRs (modifies ML Models/)
# Tests: model registration + model card + data card + backdoor scan
# Validates: MLflow champion/challenger pattern
# Requires: Neural Cleanse pass for promoted FM checkpoints
```

### `.github/workflows/vnext-contract-db.yml`
```
# Runs on schema-changing PRs
# Validates: Alembic migration is additive-only
# Validates: Neptune schema diff against main
# Validates: OpenAPI v1 spec unchanged
```

Existing workflows (`shiki-e2e.yml`, `repo-health.yml`) continue unchanged.

---

## Artifact signing

Every build artifact (container, model, SDK bundle) is signed:

```
# In CI, after successful build
cosign sign --key env://COSIGN_KEY $IMAGE_URI
cosign attest --key env://COSIGN_KEY \
  --predicate sbom.cyclonedx.json \
  --type cyclonedx \
  $IMAGE_URI

# At runtime, verify before pull
cosign verify --key $PUB_KEY $IMAGE_URI
```

Artifacts without valid signatures are refused at deploy time.

---

## SBOM generation

Per build:
- Python: `pip-licenses` + `cyclonedx-py`
- Node: `@cyclonedx/cyclonedx-npm`
- Container: `syft`

SBOM stored alongside artifact; signed; queryable for CVE audits.

---

## Secrets management

| Secret type | Storage | Rotation |
|---|---|---|
| Service creds | AWS Secrets Manager | 30 days |
| Signing keys (attestation) | HSM (CloudHSM) | 24 hours |
| SDK root keys | KMS + device-bound | Signed manifest rotation |
| CI tokens | GitHub OIDC (no long-lived) | Per-run |
| MLflow write access | IAM role w/ MFA | Per-session |
| Neptune creds | IAM | 30 days |

**No secrets in env files committed to repo.** All loaded at runtime via secret broker.

---

## Deployment strategy

### Staging
- Auto-deploy on merge to integration branch
- Feature flags on per-pillar basis
- Smoke tests run post-deploy
- Shadow lake available for sim testing

### Production
- Canary deploy (5% → 25% → 50% → 100%)
- Feature flags default off for all tenants
- Per-tenant opt-in to v-Next features
- Observability gate: rollback if error rate > 0.1% or P95 regression > 20%

### Rollback mechanics
```
# Global kill switch
export VNEXT_GLOBAL_KILL=true  # disables all vnext flags

# Per-pillar disable
export FF_VNEXT_MISSION_GRAPH_ENABLED=false

# Canary rollback
kubectl rollout undo deploy/aether-backend
```

---

## Observability requirements

Every new code path emits:

| Metric | Type | Cardinality |
|---|---|---|
| `vnext_requests_total{endpoint,tenant,flag_enabled}` | counter | Low |
| `vnext_request_duration_seconds{endpoint}` | histogram | Low |
| `vnext_errors_total{endpoint,error_type}` | counter | Low |
| `vnext_feature_flag_check{flag,result}` | counter | Low |
| `vnext_ml_inference_duration{model}` | histogram | Low |
| `vnext_conformal_abstention{model}` | counter | Low |
| `vnext_signature_verify{result}` | counter | Low |
| `vnext_mutation_auto_approved{class,approved}` | counter | Low |

Dashboards:
- Pillar health dashboard per pillar
- Feature flag rollout dashboard
- Security event dashboard (extraction alerts, MIA attempts)
- ML model drift dashboard

---

## Model deployment workflow (MLflow)

```
Developer commits ML change
  │
  ▼
CI runs training on sampled data
  │
  ▼
MLflow registers as "challenger" model
  │
  ▼
Shadow deploy (mirrors prod traffic, no user impact)
  │
  ▼
Metrics comparison vs champion (A/B)
  │
  ▼
Security checks: Neural Cleanse, STRIP, backdoor scan
  │
  ▼
Model card + data card review (human)
  │
  ▼
Promotion to champion
  │
  ▼
Canary serve (5% → 100%)
  │
  ▼
Post-promotion monitoring
```

---

## Blocked operations in CI

CI automatically blocks PRs that:

| Violation | Detection |
|---|---|
| Drop/rename DB columns | Alembic migration lint |
| Modify /v1 response shapes | OpenAPI diff |
| Change existing graph type semantics | Neptune schema diff |
| Remove existing controllers | File exists check |
| Commit secrets | gitleaks + trufflehog |
| Commit unsigned Docker images | cosign verify step |
| Promote ML model without model card | Model card checker |
| Introduce unpinned dependencies | pip-audit + lockfile check |
| Remove existing tests | Test count regression check |

---

## Release versioning

v-Next features ship as minor versions atop v8.8.0:

- `v8.9.0-vnext.0` — P0 Foundation only
- `v8.9.0-vnext.1` — + P7 Provenance
- `v8.9.0-vnext.2` — + P1 Mission Graph
- ... etc

Every release tag includes:
- Pillar status manifest (`vnext-pillars.json`)
- Feature flag registry snapshot
- SBOM
- Signed artifacts
- Model card bundle
