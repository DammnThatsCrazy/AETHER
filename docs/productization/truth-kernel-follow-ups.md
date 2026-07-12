---
title: Truth Kernel — Documented Follow-Ups
slug: operations/truth-kernel-follow-ups
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# Truth Kernel — Documented Follow-Ups

The Truth Kernel release-hardening pass landed the contract spine, SDK runtime
parity, financial value semantics, and additive tenant-policy/identity evidence.
The systems below are **intentionally out of scope** for that pass because each
is net-new, multi-week platform work; building them as placeholder-only modules
was explicitly avoided. Current paths remain **fail-closed** (unknown → deny /
exclude / review), never silently bypassed.

Do not claim these as production-ready until they are actually implemented and
supported by the `scripts/production_status.py` scorecard.

## Deferred systems

| System | Fail-closed today | What the follow-up adds |
|---|---|---|
| **`TrainingDataGate`** | Model training paths are not auto-fed from restricted data; the feature/model registries exist | Required training manifest in staging/prod; blocks synthetic-in-prod, restricted-purpose features, DSR/suppressed subjects, missing privacy/bias/model/dataset artifacts |
| **`InferencePolicyGate`** | Inference is served behind existing tenant/actor auth | Per-request gate on consent, feature policy, model governance, DSR/suppression/retention/artifact state; denies or redacts forbidden features |
| **Backend-unified DSR propagation map** | DSR erasure cascades via `GDPR & SOC2/aether-compliance` `GDPR_DATA_STORES`; suppression + identity split invalidate downstream where possible | A backend propagation-record map across aliases/graph/Profile360/features/training sets/artifacts/exports/replay/reward/attribution/value snapshots with per-step status |
| **Kyber command center (policy/model/DSR/metering)** | Kyber operator entry is authorized (`is_platform_admin`) and audited | Operator surfaces for blocked training, stale artifacts, feature-policy violations, identity/source conflicts, DSR failures, metering anomalies, valuation exclusions |
| **Metering evidence + quota controls** | Usage is metered; billing paths exist | Per-event `metered_event_id` explainability (billable/excluded reason, dedupe) and exposed quota/rate-limit states |
| **Durable valuation tables + live price sources** | `services/value` prices on-the-fly (USD identity / provider-reported / unpriced≠0) with deterministic CI fixtures | Additive `price_snapshots` / `valuation_snapshots` / `value_rollup_snapshots` tables + FX/market/peg price-source adapters with TTL caching |
| **Broad economic-surface value adoption** | Profile360 financials + contextual panels render via the canonical value contract; the guardrail blocks new local formatters | Retrofit derivatives / card-linked / campaigns / TVL / LTV / x402 / Kyber diagnostics onto `AetherValue` (tracked by the `validate_frontend_value_display.py` allowlist) |

## Landed in follow-up PRs

- **Central consent `PolicyDecision` service** (`services/policy/`): the first
  runtime consumer of the signal-use matrix. `consent_policy_engine.decide(...)`
  produces an explainable, persisted `ConsentPolicyDecision` (allow-with-id /
  deny+reason / redact+fields) that joins the tamper-evident security audit
  ledger; read-only evidence at `GET /v1/policy/decisions`. Wired additively at
  the Profile360 web2/credit gate. No broad-consent fallback — exact required
  purpose per signal/purpose.

## Landed this pass (for reference)

- Contract spine + unbypassable repo gates; registry-derived consent (no hardcoded count).
- SDK `observe()` + canonical ecommerce + registry-derived consent map; native/server parity + bug fixes.
- Canonical value semantics; Profile360 cross-currency float-summation blocker fixed; USD-first rollups; frontend `ValueDisplay` + guardrail.
- Signal-use matrix (exact purpose per signal, no broad-consent fallback).
- Strong (probabilistic) identity auto-linking off by default in staging/production (deterministic unaffected; explicit env opt-in re-enables).
