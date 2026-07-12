---
source_files:
  - Backend Architecture/aether-backend/services/model_governance/consent_purposes.py
  - Backend Architecture/aether-backend/services/model_governance/contracts.py
  - Backend Architecture/aether-backend/services/model_governance/policy.py
  - Backend Architecture/aether-backend/services/model_governance/training_gate.py
  - Backend Architecture/aether-backend/services/model_governance/inference_gate.py
  - Backend Architecture/aether-backend/services/model_governance/repositories.py
  - Backend Architecture/aether-backend/services/ml_serving/routes.py
last_synced_commit: "fabddb8"
---

# Model Governance — Source of Truth

Consent-scoped admission of data into model **training** and consent-scoped,
audited model **inference**. Model training and serving are sensitive actions:
they are gated by the same canonical consent `PolicyDecision` engine
(`services/policy`) as every other sensitive path, so their decisions land in the
same tamper-evident audit ledger and `/v1/audit` export.

Purpose semantics are never hardcoded — they are read from the canonical consent
registry (`packages/shared/contracts/consent-registry.json`) at runtime by
`services/model_governance/consent_purposes.py`.

## Training-data admission (§3.5 / §3.10)

`TrainingDataGate` partitions candidate training records into **admitted** and
**quarantined** sets. A record is quarantined (fail-closed) when:

| Condition | Reason code |
|---|---|
| No declared source purpose (provenance-less) | `no_source_purpose` |
| Purpose whose `allowModelTraining` is false and has no opt-in path (`web3`, `credit`, `location`) | `purpose_forbids_training:<purpose>` |
| Purpose that needs a *separate* model-training opt-in the caller lacks (`financial_activity`, `economic_observability`, `cross_chain_observability`) | `separate_opt_in_required:<purpose>` |
| Purpose outside the model's declared `allowed_training_purposes` scope | `purpose_not_allowed_for_model:<purpose>` |
| Identity-derived label (`label_source == "identity_resolution"`) with no admissible source purpose (§3.10) | `identity_label_unconsented` |

Purposes carrying `modelTrainingPermission: separate_opt_in_required` are trainable
**only** when the caller passes the matching opt-in (`granted_training_opt_ins`),
regardless of the purpose's default `allowModelTraining` flag. Every decision
(admitted and quarantined) is persisted as durable provenance evidence
(`model_training_decisions`, tenant-scoped).

## Inference policy gate (§3.9)

`InferencePolicyGate.evaluate(...)` is invoked by the ML serving `predict` route
(`services/ml_serving/routes.py`) immediately after canonical model resolution.
It **always** records a `serve_inference` consent `PolicyDecision` (the engine
persists these unconditionally), and returns an `InferenceGateResult`.

Enforcement precedence (`policy.inference_enforcement`):

1. explicit caller `enforce=` override;
2. `ML_INFERENCE_POLICY_ENFORCE=true` process env (operator switch);
3. the model registry's `fail_closed_required` flag.

Default is **evidence-only** so enabling the gate never breaks live inference
before subject-consent plumbing is complete end-to-end; models flagged
`fail_closed_required` in the ML registry still fail closed. When enforced and the
subject is missing a required purpose, the route returns `403` and increments
`ml_inference_consent_denied`. The `policy_decision_id` is echoed on the
prediction response for traceability.

Required serving purposes are resolved from the ML registry governance metadata
(`ModelEntry.allowed_training_purposes` / category mapping) via
`services/model_governance/policy.py`, with a conservative static fallback when
the ML package is not importable in-process.

## Gates

- `scripts/validate_model_governance.py` — backend enforcement surface: the
  gates exist, reuse the consent engine, and are wired into the predict route.
- `scripts/validate_ml_registry.py` — the ML registry's per-model governance
  metadata (sensitivity tier, promotion requirements, model/dataset cards).

Both run in `make ci-check` via `scripts/repo_doctor.py`.
