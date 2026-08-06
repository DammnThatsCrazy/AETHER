---
title: Computation Substrate
slug: source-of-truth/computation-substrate
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/computation/__init__.py
  - Backend Architecture/aether-backend/shared/computation/types.py
  - Backend Architecture/aether-backend/shared/computation/result.py
  - Backend Architecture/aether-backend/shared/computation/context.py
  - Backend Architecture/aether-backend/shared/computation/definition.py
  - Backend Architecture/aether-backend/shared/computation/registry.py
  - Backend Architecture/aether-backend/shared/computation/allocation.py
  - Backend Architecture/aether-backend/shared/computation/aggregation.py
  - config/computation_inventory.yaml
  - scripts/validate_computation_substrate.py
canonical_owner: platform@aether
---

# Computation Substrate

The **AETHER Computation Substrate** (`shared/computation` + `services/computation`)
is the single governed contract under which every material platform number is
defined, typed, scoped, versioned, explainable, quality-aware, uncertainty-aware,
restatable, and consistent wherever it appears.

It **generalizes** the Measurement Integrity Plane (`shared/measurement`) and
**composes** the financial value semantics (`services/value` / `packages/shared/value.ts`),
the dimension-state envelopes (`shared/dimension_state`), and the Temporal
Integrity kernel (`shared/temporal`). It does not replace or duplicate them.

## Non-negotiable principles

1. **Unknown is never zero.** A missing/unavailable/failed/insufficient input is a
   result with a `null` value and an honest status — never a numeric `0`. A `0`
   is permitted only under an evidence-backed `available` status.
2. **Every number knows what it is.** Every `CanonicalResult` carries its
   definition identity + version, run id, mathematical type, unit, currency,
   status, numerator/denominator, quality, uncertainty, lineage, and correction
   chain.
3. **Mathematical kinds are not interchangeable.** Observed facts, deterministic
   metrics, allocated values, heuristic scores, statistical estimates, calibrated
   probabilities, forecasts, reconciled values, ranks, percentiles, and graph
   metrics are distinct `ComputationKind`s. A heuristic score is not a
   probability; an allocated cost is not an observed cost.
4. **Money uses Decimal semantics.** Money is a Decimal/decimal-string plus a
   required currency, never a binary `float`; mixed native currencies are never
   raw-summed into a scalar.
5. **Time is explicit.** Windows/watermarks/as-of are built on `shared/temporal`;
   there is no ad-hoc `datetime` math in the substrate.
6. **Bounded reads disclose truncation.** A page total is never reported as a
   population total (`lineage.BoundedReadDisclosure`).
7. **Definitions and policies are versioned separately.** A definition says what a
   number is; a `DecisionPolicy` says what to do with it.
8. **Historical truth is preserved.** Corrections supersede (never overwrite),
   referencing the prior result and reason.

## Mathematical types (`types.py`)

`Money`, `Rate`, `Ratio`, `Percentage`, `IntegerCount`, `FractionalCount`,
`Probability`, `OrdinalScore` / `HeuristicScore` / `UncalibratedScore`, `Rank`,
`Percentile`, `Distribution`, `Interval`, `Vector`, `GraphMetric`, `Duration`,
`Quantity`, `Balance`, `TriState`, `TimestampedValue`. Each declares its
serialization, bounds, and null behavior. Key invariants: money rejects floats
and requires a currency; probability is bounded `[0,1]` and declares whether it
is calibrated; a rate exposes its numerator and denominator; a graph metric
identifies its snapshot and normalization population.

## Result states (`result.py`)

`CanonicalResult.status` is one of: `available`, `partial`, `estimated`,
`insufficient_data`, `missing_inputs`, `not_applicable`, `not_provisioned`,
`unavailable`, `stale`, `conflicted`, `unreconciled`, `truncated`,
`privacy_restricted`, `suppressed`, `failed`. `available` requires a value; the
honest-absence statuses forbid one. A model validator enforces this at
construction, so "unknown" can never be serialized as `0`.

## Definition versioning (`definition.py`, `registry.py`)

A `ComputationDefinition` is immutable once `active`: any change to formula,
denominator, scope, allocation, source, precision, threshold interpretation, or
window semantics requires a **new version**. The hand-authored registry is
mirrored by a generated twin (`generated_registry.py`, produced by
`scripts/generate_computation_registry.py`) kept in parity by
`tests/computation/test_registry_parity.py` and the CI gate.

## Context (`context.py`)

`ComputationContext` is an immutable scope descriptor (tenant, subject/population,
grain, dimensions, event-time window + as-of + timezone + watermark, native/
reporting currency, and identity/model/policy/consent versions). Its
`context_hash()` is the deterministic dedupe/supersession key. No canonical
computation reads scope implicitly from process globals or the wall clock.

## Aggregation algebra (`aggregation.py`)

Legal aggregations are named (`AggregationType`). Rates aggregate as
**ratio-of-sums**, never average-of-averages; mixed-currency raw sums and
balance/TVL snapshot sums are refused.

## Allocation (`allocation.py`)

The allocation engine distributes a source amount under a policy (equal,
proportional, time-weighted, usage-weighted, attribution-credit, contractual,
custom) and **guarantees** `sum(allocated) + residual == source`. Allocated
slices are `estimated`, never `observed` — this is the fix for journey/entity
campaign cost that previously duplicated full campaign spend.

## Reconciliation (`reconciliation.py`)

`ReconciliationCase` compares a derived value against an authority with a recorded
tolerance and rationale; a value is not "reconciled" merely because a formula ran.

## Calibration (`calibration.py`)

`CalibrationArtifact` + Brier / expected-calibration-error metrics. Heuristic
scores that are not empirically calibrated are typed `OrdinalScore` /
`HeuristicScore` / `UncalibratedScore` and must not claim to be probabilities.

## Persistence & runs (`services/computation/repositories.py`)

Canonical results are stored immutably in `computed_results` (Alembic migration
`20260815_computation_substrate`), with at most one *active* row per
`(tenant_id, definition_id, definition_version, context_hash)` (partial unique
index). `computation_runs` records the run that produced a result;
`computation_restatements` is the supersession audit trail. The repo follows the
DDL-parity idiom (repo constants asserted equal to the migration) and the dual
local/asyncpg backend.

## Explain API (`services/computation/routes.py`, mounted at `/v1/computations`)

Read-only, tenant-scoped endpoints:

- `GET /v1/computations/definitions` and `/definitions/{id}` — the canonical
  registry;
- `GET /v1/computations/results` and `/results/{id}` — stored canonical results;
- `GET /v1/computations/results/{id}/explain` — answers *what is this number?*
  (definition version, formula/kind, inputs, window, observed vs allocated vs
  estimated vs reconciled, completeness, staleness, uncertainty, supersession
  chain);
- `GET /v1/computations/runs/{id}` — the producing run.

## Restatement

Corrections create a new result that supersedes the prior one (`supersedes_result_id`
+ `restatement_reason`), reusing the measurement plane's supersession discipline.
The repository's `supersede()` stamps the prior active row and records a
restatement, so historical truth is preserved and `/explain` can show the chain.

## Presentation rules (`serialization.py`)

`presentation_metadata()` gives the frontend the display value, unit, currency,
status, and any warning (stale/partial/estimated/allocated/truncated). Frontends
FORMAT values; they never recompute or reinterpret them.

## Governance

- **CI gate:** `scripts/validate_computation_substrate.py` (wired into
  `make ci-check` via `scripts/repo_doctor.py`) enforces registry parity + version
  discipline, active-definition owner/tests, `config/computation_inventory.yaml`
  consistency, and a shrink-only money-as-float ban over the governed dirs.
- **Discovery inventory:** `config/computation_inventory.yaml` is the machine-
  readable ledger of material computations and their migration state (shrink-only
  for un-migrated debt).
- **Ownership:** the `computation_substrate` change-category in
  `docs/source-of-truth/repo_consistency_ownership.json`.

## Domain migration status

| Domain | State | Notes |
| --- | --- | --- |
| Campaign / gold economics | in progress | canonical definitions registered; gold materializer routed through the substrate (fractional conversions, null-not-zero ratios, allocated journey cost) |
| Financial value (net worth / net TVL / net LTV) | in progress | unpriced-subtrahend fixes (partial, not inflated) |
| P&L, billing/metering | roadmap | recorded in `config/implementation_ledger.yaml` |
| Trust / fraud / identity | roadmap | trust vector, fraud calibration, identity evidence + merge restatement |
| Behavioral / graph / ML | roadmap | opportunity model, graph snapshot governance, prediction cache/envelope |
| Agent / operational | roadmap | observed vs verified vs estimated vs counterfactual outcomes |

The authoritative, up-to-date migration state lives in
`config/computation_inventory.yaml` and `config/implementation_ledger.yaml`.
