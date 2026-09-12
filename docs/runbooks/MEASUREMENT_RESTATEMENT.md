---
title: Runbook — Measurement Restatement
slug: runbooks/measurement-restatement
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 2
source_files: [Backend Architecture/aether-backend/repositories/measurement_results_repo.py, Backend Architecture/aether-backend/shared/measurement/restatement.py, Backend Architecture/aether-backend/shared/measurement/compute.py, Backend Architecture/aether-backend/services/measurement/routes/integrity.py, Backend Architecture/aether-backend/services/traffic/repair.py]
source_hashes:
  Backend Architecture/aether-backend/repositories/measurement_results_repo.py: sha256:35a40c028d487f0bbe1b1d19cf3f542c1e0212ff13d40693ad443cbb9ec3f906
  Backend Architecture/aether-backend/services/measurement/routes/integrity.py: sha256:a0b5704ca62eb3b7fd7bf9e066559c228ecbdc772c16967627713ab690cb6a47
  Backend Architecture/aether-backend/services/traffic/repair.py: sha256:b1f732c004b51f42e9b16635516bcd9ce92682a40d6f33d51e735d5f2f107df0
  Backend Architecture/aether-backend/shared/measurement/compute.py: sha256:b572af2401ba87547852aa1b44fc5687b66291274a92b1aace752d8e103a90cc
  Backend Architecture/aether-backend/shared/measurement/restatement.py: sha256:1217bf79afa2c8cb11bd36908aebf616953c382822098f493cc2d8b8a58b8428
---

# Runbook — Measurement Restatement

Correct a published measurement result **without ever editing or deleting the
original**. A measurement result is immutable; the only sanctioned change is a
*restatement* — the prior row is stamped `superseded_by`, a fresh active row
takes its place, and an audit record links them. Every number's full history
stays recoverable.

## When a restatement is warranted

- Late-arriving data changes a computed value (e.g. conversions that landed after
  the window closed).
- An input correction (a fixed spend feed, a corrected consent state).
- A metric-definition or attribution-model change that alters how a value is
  computed for a context.

Do **not** restate to "clean up" a value you dislike — restatements are audited
and every prior value remains visible via the explain surface.

## Before you restate

1. **Identify the active result.** `GET /v1/measurement/results?metric_name=…`
   (tenant-scoped, active by default) → find the result id.
2. **Read its derivation.** `GET /v1/measurement/results/{id}/explain` → value +
   `value_state`, lineage, sufficiency, uncertainty, and the current restatement
   chain. Confirm the value is genuinely wrong (not merely `insufficient_data`,
   which is the honest state for a below-floor sample — that is not a defect).

## Perform the restatement

Restatements go through the repository's `supersede(...)`
(`repositories/measurement_results_repo.py`), which is atomic under Postgres:

1. Build the new `MeasurementResult` for the **same** `(tenant, metric_name,
   metric_version, context_hash)` — same context, corrected value + `value_state`
   (never a bare `0` on missing data; use `insufficient_data`/`missing_inputs`
   with `value=None` when that is the truth).
2. `supersede(tenant_id, prior_result_id, new_record, reason=…)` stamps the prior
   row's `superseded_by`, inserts the new active row, and writes a
   `measurement_restatements` record (`build_restatement`) with the human reason.
   A partial unique index guarantees exactly one active result per context, so a
   concurrent double-restate fails closed rather than forking history.
3. A `MEASUREMENT_RESTATED` event is emitted for downstream recompute/audit.

## Verify

- `GET /v1/measurement/results/{id}/explain` on the **new** result → its
  `restatement_chain` shows ≥2 entries (prior → new) and `superseded` is true on
  the old one. The prior value is still readable with `include_superseded=true`.
- Confirm the new `value_state` is honest: `observed`/`estimated` only when the
  data supports a number; otherwise a value-less state.

## Source-classification repair

The Kyber source-classification repair job is an approved restatement producer.
After it appends corrected touchpoint classifications, it forces new journey
versions and attribution runs, expands the materialization window to include
every affected canonical conversion date, and passes a classifier-versioned
reason into Gold materialization. Existing results remain in the restatement
chain; the repaired values become the active publication.

Do not run Gold materialization alone for a source correction. That would
publish values derived from stale journeys or attribution credits. Use the
Kyber repair endpoint so classification, journey rebuild, attribution
recompute, and restatement occur in that order.

## Do NOT

- Edit or delete a `measurement_results` row directly — it breaks the audit chain
  and the active-result uniqueness invariant. Always go through `supersede`.
- Restate to force a value the data does not support. `insufficient_data` and
  `missing_inputs` are correct outcomes, not bugs — surfacing them honestly is the
  point of the Measurement Integrity Plane.

## Escalation

If `supersede` raises `ConflictError` ("already superseded") you lost a race —
re-read the now-active result and restate from it. If the chain looks
inconsistent (two active rows for one context, which the index should prevent),
capture the `measurement_results` + `measurement_restatements` rows for the
context and escalate to `platform@aether`; do not hand-edit rows.
