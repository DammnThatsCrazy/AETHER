---
title: Measurement Integrity Plane Source of Truth
status: stable
source_files:
  - Backend Architecture/aether-backend/shared/measurement/value_states.py
  - Backend Architecture/aether-backend/shared/measurement/context.py
  - Backend Architecture/aether-backend/shared/measurement/contracts.py
  - Backend Architecture/aether-backend/shared/measurement/validators.py
  - Backend Architecture/aether-backend/shared/measurement/uncertainty.py
  - Backend Architecture/aether-backend/shared/measurement/registry.py
  - Backend Architecture/aether-backend/shared/measurement/compute.py
  - Backend Architecture/aether-backend/repositories/measurement_results_repo.py
  - Backend Architecture/aether-backend/services/measurement/routes/integrity.py
last_synced_commit: pending
---

# Measurement Integrity Plane

The Measurement Integrity Plane makes one guarantee enforceable: **no metric is
reported as a real number unless the data supports it.** A calculator returns
`(value | None, ValueState)` — never `0` on missing/insufficient inputs — and
every persisted result carries the state, its lineage, its sufficiency, and its
uncertainty. Corrections happen only through an auditable restatement.

## Value states

`shared/measurement/value_states.py` — every result is exactly one of:

| State | Meaning | `value` |
|---|---|---|
| `observed` | computed from sufficient real data | required (finite) |
| `estimated` | modeled / imputed | required (finite) |
| `insufficient_data` | below the metric's minimum sample | `None` |
| `not_applicable` | the metric does not apply to this context | `None` |
| `missing_inputs` | a required input was absent | `None` |
| `degraded` | computed with quality caveats | `None` |

`requires_value(state)` is True only for `observed` / `estimated`; the
`MeasurementResult` model enforces the invariant (a value present iff the state
allows one; `NaN`/`inf` and negative counts are rejected by `validate_value`).

## MeasurementContext

`context.py` — a frozen `MeasurementContext` (tenant, window, timezone,
attribution model, registry version) with a **deterministic** `context_hash()`.
The hash keys a result to exactly the conditions it was computed under, so the
same context always resolves to the same active result and a changed context is
a different result, never a silent overwrite.

## Registry & uncertainty

- `registry.py` — the in-code metric registry (`MetricDefinition`: name, version,
  unit, bounds, `min_sample`, `allows_probability`). `REGISTRY_VERSION` pins the
  contract a result is validated against. Surfaced at `GET /v1/measurement/definitions`.
- `uncertainty.py` — `wilson_interval` (proportions) and a seeded, deterministic
  `bootstrap_ci` (means). `probability`-named metrics are gated on the registry's
  `allows_probability`; an index is never silently relabeled a probability.
- `sufficiency.py` — `evaluate_sufficiency(sample_size, min_required)` maps a
  sample below the floor to `insufficient_data` rather than a fabricated value.

## Immutable persistence

`repositories/measurement_results_repo.py` + migration `20260716_measurement_integrity`:

- `measurement_results` — real columns + JSONB lineage/sufficiency/uncertainty;
  a partial unique index on `(tenant_id, metric_name, metric_version,
  context_hash) WHERE superseded_by IS NULL` guarantees one active result per
  context. `insert_result` **rejects** an active duplicate (integrity-first).
- **Supersession is the only mutation.** `supersede(...)` stamps the prior row's
  `superseded_by`, inserts the new active row, and writes a
  `measurement_restatements` record — atomically under Postgres. Prior rows are
  never deleted or edited, so every number's history is recoverable.
- `restatement_chain(...)` returns the ordered version chain for a metric+context.

The repo DDL string is identical to the migration (parity-tested), and the
migration keeps a single alembic head.

## Read surfaces

`services/measurement/routes/integrity.py` (mounted under `/v1/measurement`):

| Route | Returns |
|---|---|
| `GET /v1/measurement/definitions` | registry version + metric definitions |
| `GET /v1/measurement/results` | tenant-scoped results (active by default; `include_superseded` for history) |
| `GET /v1/measurement/results/{id}/explain` | value + value_state, lineage, sufficiency, uncertainty, definition, and the restatement chain |

All reads are tenant-scoped (`read` permission); cross-tenant lookups return
`None` / 404.

## Engine bridge (Campaign360 → plane)

`compute.py` is the honest-computation bridge the engine calculators use:
`rate_result(numerator, denominator, metric_name=…)` returns
`(value | None, ValueState, Uncertainty | None, sufficiency)` — a value below the
metric's sample floor is `insufficient_data` with `value=None` (never a bare 0),
no sample at all is `missing_inputs`, and a sufficient bounded proportion is
`observed` with a Wilson interval. `record_rate(repo, context, …)` persists the
result into the plane, idempotently (an active result for the same context is
returned unchanged, not re-inserted).

The Campaign360 gold materializer
(`services/measurement/engine/gold_materializer.py`) uses this to record the
tenant-day `conversion_rate` into the plane on every materialization. The gold
ClickHouse row keeps its typed float column for analytical compatibility; the
plane is the **integrity source of truth** — a `0.0` in gold is legacy
denormalization, while the plane reports `insufficient_data` when there are too
few clicks to trust a rate.

## Non-goals / limitations

- The metric registry is generated from `packages/shared/contracts/metric-registry.json`
  (`measurement-contract.ts` + `generated_registry.py` + a docs table, parity-tested
  against the hand-authored `registry.py`). Threading `MeasurementContext` through
  the remaining Campaign360 calculators (attribution credits, journey economics)
  beyond the tenant-day conversion rate is the next increment.
- `MeasurementContext` grain is tenant-window (no per-campaign dimension), so the
  engine records the tenant-day aggregate conversion rate, not one per campaign.
- `bootstrap_ci` is seeded for determinism; it is not a substitute for a
  calibrated model where one is required.
