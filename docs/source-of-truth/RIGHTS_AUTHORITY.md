---
title: IRRL Rights Authority
slug: source-of-truth/rights-authority
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ops, compliance]
status: draft
canonical_owner: compliance@aether
source_files:
  - packages/shared/contracts/rights-authority-registry.json
  - packages/shared/contracts/rights-transform-registry.json
  - packages/shared/contracts/rights-activation-profile-registry.json
  - Backend Architecture/aether-backend/shared/rights_authority/contracts.py
  - Backend Architecture/aether-backend/shared/rights_authority/repository.py
  - Backend Architecture/aether-backend/shared/rights_authority/service.py
  - Backend Architecture/aether-backend/shared/rights_authority/pep.py
  - Backend Architecture/aether-backend/shared/rights_authority/remediation.py
  - Backend Architecture/aether-backend/services/ingestion/rights.py
  - Backend Architecture/aether-backend/services/olympus/gateway.py
  - Backend Architecture/aether-backend/services/model_governance/training_gate.py
  - Backend Architecture/aether-backend/services/ml_serving/routes.py
  - Backend Architecture/aether-backend/services/exploration/service.py
  - Backend Architecture/aether-backend/services/export/service.py
  - Backend Architecture/aether-backend/services/profile/routes.py
  - Backend Architecture/aether-backend/services/operational_intelligence/routes.py
  - Backend Architecture/aether-backend/services/kyber/graph/scoped_gateway.py
  - Backend Architecture/aether-backend/repositories/lake.py
  - Backend Architecture/aether-backend/repositories/artifacts.py
  - Backend Architecture/aether-backend/alembic/versions/20260903_irrl_rights_authority.py
  - Backend Architecture/aether-backend/alembic/versions/20260904_graph_rights_columns.py
  - Backend Architecture/aether-backend/alembic/versions/20260905_olympus_rights_promotion.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_irrl_evidence_remediation.py
  - Backend Architecture/aether-backend/alembic/versions/20260907_irrl_audit_outbox.py
  - Backend Architecture/aether-backend/shared/rights_authority/obligations.py
  - Backend Architecture/aether-backend/shared/rights_authority/reconciliation.py
last_synced_commit: "72d48888"
estimated_read_minutes: 9
---

# IRRL Rights Authority

The Integrated Rights and Responsibility Ledger (IRRL) is the canonical
authority for whether Aether may ingest, store, read, mutate, derive, train,
evaluate, aggregate, disclose, export, retain, delete, or operate a Kyber
tenant scope. Aether is the external platform. Kyber remains an internal
operator/control plane and is never exposed as a customer or partner product.

This document describes the code currently present on the branch. It is not a
legal determination and does not replace contract, consent, privacy, or
security review.

## Authority records

The hand-authored JSON registries are the vocabulary source of truth. The
generator produces the TypeScript/Python registry twins and the generated
table. The durable PostgreSQL ledger has append-only records for:

| Record | Purpose | Current implementation |
|---|---|---|
| Policy set | Agreement, effective dates, allowed uses, approvals, retention, activation state | `irrl_policy_sets` |
| Artifact envelope | Rights class, holder, source grants, consent/license/classification refs, lineage roots, retention and disclosure ceiling | `irrl_artifact_rights_envelopes` |
| Decision | Signed allow/deny/obligation/unavailable result bound to a request id | `irrl_rights_decisions`, `irrl_rights_audit_outbox` |
| Derivation edge | Parent-to-child lineage and transform proof reference | `irrl_derivation_edges` |
| Revocation/impact | Revocation fan-out and affected artifact plan | `irrl_revocations`, `irrl_impact_graphs` |
| Evidence manifest | Signed consent/license/approval/classification evidence references | `irrl_evidence_manifests` |
| Remediation | Attempt state and receipt for quarantine, deletion, recomputation, or retraining | `irrl_remediation_steps`, `irrl_remediation_receipts` |
| Source grant | Compatibility facade for connector-level lake/graph/training/aggregate permissions | `irrl_source_grants` |

The repository is durable in staging/production when PostgreSQL is available;
the in-memory repository is an explicitly local/test backend. A decision is
idempotent by `request_id`, and its HMAC signature carries a key id. The
signing key is domain-separated for IRRL decisions. Operators can verify a
historical key during rotation through `AETHER_RIGHTS_SIGNING_KEYS`; staging
and production must provide signing material through the configured secret
path rather than the local development fallback.

## Effective decision

`RightsAuthority.evaluate()` intersects all available authority inputs before
returning a decision:

1. The action must exist in the canonical registry and be permitted by the
   effective policy profile and purpose.
2. Required envelopes, source grants, tenant matches, activation/effective
   dates, deletion state, retention deadlines, and revocations must pass.
3. Agreement acceptance, actor kind, destinations, sovereignty regions,
   required signatories/approvals, consent snapshots, source licenses,
   classifications, and retention evidence are checked when required by the
   policy constraints.
4. Derived use must name a registered transform and satisfy its input-class,
   evidence, approval, aggregate-threshold, privacy, re-identification, and
   release-proof requirements.

Expected policy denials are signed `deny` decisions. Missing authority or
ledger/signing/audit dependencies produce `unavailable`; they are not
converted into an empty result or a successful write.

## Enforcement points

The policy-enforcement point is applied at the material side-effect boundary:

- SDK and provider ingestion authorizes `ingest` and `store` before Bronze,
  raw-event, identity, or outbox persistence.
- Bronze, Silver, Gold, export artifacts, and feature materialization require
  a rights context in enforce mode; the context is reference-only and never
  contains plaintext secrets.
- Graph mutations pass through `GraphMutationGateway`, which evaluates
  `graph_mutate` and stamps decision/envelope references. Direct graph writer
  paths are frozen at zero by the allowlist gate.
- Explore and saved views authorize before an adapter executes and return an
  explicit suppressed/pending/unavailable state when the request cannot run.
- Profile360, operational graph reads/exports, Kyber scoped reads, model
  training, model evaluation/inference, and feature reads authorize before
  composition, adapter calls, or decision-aware caches.
- Olympus generalized promotion requires a registered transform, threshold,
  privacy/re-identification evidence, approvals, and a release proof. Its
  persistent kill switch blocks enqueue and processing while frozen.

Rollout is controlled by `AETHER_RIGHTS_AUTHORITY_MODE`: `off` is local-only
compatibility behavior, `shadow` records decisions without blocking, and
`enforce` blocks non-allow outcomes. Production defaults to `enforce` when the
mode is not explicitly set.

## Revocation and lifecycle

Revocation records the roots and descendants in an impact graph. The
remediation coordinator records every step and receipt. Without a concrete
storage/search/vector/model adapter callback, the step and impact remain
`blocked`; no worker or endpoint fabricates a completed deletion or
recomputation. Account deletion and DSR completion likewise wait for their
underlying remediation receipts.

The activation, policy, evidence, decision, impact, and remediation APIs are
tenant-scoped. Operator views live under Kyber-admin routes and require the
existing Kyber operator authorization.

## Remaining release gates

The branch contains the implementation seams and local behavior tests, but a
production readiness claim still requires operational evidence outside this
repository change:

- run the Alembic chain against the target PostgreSQL and verify tenant
  isolation/RLS at the connection pool boundary;
- provision and rotate signing keys through the real secret manager;
- register concrete quarantine/deletion/recompute/retrain adapters for every
  persistent store, including object/search/vector/replay/cache providers;
- validate provider contract/license/consent evidence and legal/product policy
  choices with the owning teams;
- run shadow-to-enforce migration reconciliation and adversarial staging
  scenarios, then attach the release evidence and alert/runbook records.

Local test results and a committed branch do not constitute deployment,
staging, hosted CI, or production evidence.
