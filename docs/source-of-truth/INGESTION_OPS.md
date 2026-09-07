---
title: Ingestion Operations — Control Plane + SDK Version-Compatibility Tiers
slug: architecture/ingestion-ops
section: architecture
visibility: I
audience: [architect, dev-senior, ops, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
estimated_read_minutes: 12
toc_depth: 3
---
# Ingestion Operations — Control Plane + SDK Version-Compatibility Tiers

Source of truth for the **Operations** (WS-E) slice of the universal-ingestion
alignment: the Kyber **ingestion control plane** that closes blueprint Gate G
(source/schema health, ingestion lag, quality, rejection, replay, lineage) and
the **SDK version-compatibility tier model** that closes Gate H (previous
supported SDK versions continue functioning). This document is authored
alongside the two repo-doctor validators that enforce these surfaces as real
gates:

* `scripts/validate_kyber_ops_surface.py` — **Gate G** (Operations): the seven
  facets must resolve to real, mounted, operator-only surfaces.
* `scripts/validate_sdk_compat_tiers.py` — **Gate H** (Compatibility): the tier
  table preserves served bands and enforcement stays fail-closed by date behind
  a new default-OFF flag.

Every behavior-changing mechanism in this slice ships behind a **new default-OFF
flag**; there is no production default flip. OFF reproduces the baseline exactly
(every SDK client treated identically, zero observability recording, every
surface reporting the feature disabled).

## 1. Flags

| Flag | Default | Meaning |
|---|---|---|
| `AETHER_INGESTION_OBSERVABILITY_ENABLED` | `false` | ON: record per-stage ingestion-funnel telemetry + per-observation inspector traces (in-process ledger). OFF: no recording; every observability surface reports `enabled: false` / disabled with zeroed counters. |
| `AETHER_SDK_VERSION_COMPAT_ENABLED` | `false` | ON: ingestion consults each event's `context.library.version` and attaches an advisory tier label (`normalized["sdk_tier"]`) to accepted payloads. OFF: no consultation (all clients identical). |
| `AETHER_SDK_VERSION_COMPAT_MODE` | `off` | Enforcement switch for the ingress consultation once `ENABLED` is ON: `off`/`shadow`/`warn` = advisory attach only (identical behavior, differing recorded mode); `enforce` = additionally REJECTS events whose SDK band is past its `blocked_after` date. OFF mode never blocks. |

Declared in `config/settings.py`
(`IngestionObservabilityConfig` / `SdkVersionCompatibilityConfig` under the root
`Settings`), `.env.example`, and `.env.production.example`. Gate H validator
checks all three declarations + both env examples on every run.

## 2. Ingestion funnel telemetry + Observation Inspector (blueprint §17)

`services/ingestion/ingestion_observability.py` records **two complementary
views** when the observability flag is ON:

* **Funnel** — per-stage aggregate counters over the blueprint stage vocabulary.
* **Observation traces** — one journey per observation, keyed
  `{tenant_id}:{event_id}`, bounded in-process (2 000 traces, LRU eviction).

### Stage vocabulary and monitored set

The full blueprint §17 ladder is declared so the control plane renders every
stage honestly. Only a subset is **monitored** (actually recorded) by this
build:

| Stage | Display | Monitored | Recorded by |
|---|---|---|---|
| `raw` | RAW | no | client-side; never observed server-side |
| `received` | RECEIVED | yes | API process (`ingest_events`) at loop top |
| `validated` | VALIDATED | yes | API process (per-result disposition) |
| `bronze` | BRONZE | yes | API process (accepted rows) + `record_degraded` flat-path fallback |
| `normalized` | NORMALIZED | yes | ingestion worker `silver_normalizer` after Bronze → Silver upsert |
| `resolved` | RESOLVED | no | downstream of this slice (declared, not instrumented) |
| `relationships` | RELATIONSHIPS | no | downstream of this slice (declared, not instrumented) |
| `graph_mutations` | GRAPH MUTATIONS | no | downstream of this slice (declared, not instrumented) |
| `projections` | PROJECTIONS | yes | ingestion worker `silver_fact_projector` after outcome results persist |
| `metrics_findings` | METRICS / FINDINGS | no | downstream of this slice (declared, not instrumented) |

Per-stage dispositions: `accepted` · `duplicate` · `rejected` · `degraded` ·
`observed`. The funnel **rollup** exposes the operator-critical counts the
control plane renders: `received`, `accepted`, `duplicates`, `rejected`,
`degraded`.

### Honest scope

* RAW is client-side and never observed here — the first recorded stage is
  RECEIVED, matching where the backend first touches the observation.
* Stages past PROJECTIONS (RESOLVED → METRICS/FINDINGS) happen downstream of
  this slice; they are declared for the ladder and each stage bucket reports
  `monitored: false` so a rendered funnel never overclaims coverage.
* The ledger is **in-process**, mirroring the existing in-process
  `MetricsCollector` conventions in `shared/logger/logger.py`. Recording is a
  pure side channel: it never changes event dispositions, never rejects, and
  no-ops on a single boolean check while OFF. In a multi-process deployment each
  process aggregates what it observes; durable cross-worker tracing is a
  documented follow-on, not this slice.

### Recording seam

* `record_stage(*, tenant_id, event_id, event_type, stage, status, path, detail)`
  — funnel bucket + trace span. No-op while OFF; unknown stages ignored.
* `record_degraded(tenant_id, event_id)` — funnel degraded counter + a
  `bronze`/`degraded` span for a flag fail-open degrade (envelope/gateway
  rejected → flat SDK path).

Worker functions in `services/ingestion/workers.py` record NORMALIZED (after the
Bronze → Silver `upsert_record`) and PROJECTIONS (after `silver_fact_projector`
outcome results persist) when the flag is ON.

## 3. Kyber ingestion control plane surfaces (Gate G)

All Kyber-scoped operator surfaces are **read-only** and **Kyber-operator-only**
(router-level `require_kyber_operator`, which the default-deny route-policy
registry also classifies as audited + high-risk). Routers stay mounted so gateway
discovery sees them; bodies are flag-gated (report `enabled: false` while OFF)
— the same adoption posture as the replay kill switch.

| Surface | Method · path | Facet(s) | Notes |
|---|---|---|---|
| Ingestion observability status | `GET /v1/kyber/ingest/observability` | — | Ledger switch + monitored / declared-unmonitored stages + scope |
| Funnel telemetry | `GET /v1/kyber/ingest/observability/funnel` | quality, rejection, ingestion lag | Rollup + per-stage disposition buckets + `monitored` flags |
| Observation Inspector (one) | `GET /v1/kyber/ingest/observability/traces/{event_id}?tenant_id=` | lineage | The §17 ladder for one observation (`{trace}` or `{trace: null}`) |
| Observation Inspector (recent) | `GET /v1/kyber/ingest/observability/traces?limit=` | lineage | Bounded recent traces (LRU order) |
| Pipeline health | `GET /v1/health/pipeline` | source health, ingestion lag | Funnel summary; `healthy` / `degraded` / `disabled`; NOT operator-gated (liveness + operator hook both read it) |
| SDK capability manifest | `GET /v1/config/sdk/versions` | schema health | Static tier table + `enabled`/`mode`; NOT operator-gated (SDKs read it) |
| SDK signed manifest | `GET /v1/config/sdk/manifest` | schema health | Existing signed manifest surface |
| Replay service status | `GET /v1/kyber/ingest/replay/status` | replay | Durable Bronze replay service status |
| Replay run/preview | `POST /v1/kyber/ingest/replay/events` | replay, rejection | Operator-triggered replay / dry-run of durable Bronze rows |

`GET /v1/health/pipeline` (in `services/gateway/routes.py`) fixes the
previously-**phantom** pipeline health endpoint the Kyber operator hook called:
it now resolves and returns a 200-shaped payload from `pipeline_snapshot()`
(probe `ingestion-pipeline`, status `healthy`/`degraded`/`disabled`). While the
observability flag is OFF it reports `enabled: false` with zeroed counters so
the liveness surface stays stable.

Route policy: the observability + replay routers are registered for Kyber
operator-required / audit / high-risk; health and manifest routes are
public/tenant route-policy, never operator-gated (liveness and SDKs read them).

## 4. SDK version-compatibility tiers (Invariant #18 / Gate H)

`services/ingestion/sdk_version_tiers.py` declares the honest version-band model
behind the capability manifest. Today the backend strips
`context.library.version` and treats every SDK client identically; this module
declares the bands, the per-band capability set, and the **advisory** ingress
consultation that is inert by default.

### Tier table (authoritative)

| Tier | Version range | Capability set | Enforcement |
|---|---|---|---|
| `supported` (8.x) | `[8.0.0, ∞)` | FULL: `batch_ingestion` · `server_side_ingestion` · `canonical_observation_envelope` · `normalization_spine` · `idempotent_replay` | none |
| `deprecated` (7.x) | `[7.0.0, 8.0.0)` | FULL (still fully served) | none — `deprecated_after` `2027-06-30` is advisory |
| `read_compatible` (6.x) | `[6.0.0, 7.0.0)` | FLAT (pre-Envelope-B): `batch_ingestion` · `server_side_ingestion` · `idempotent_replay` | none |
| `blocked` (5.x) | `[5.0.0, 6.0.0)` | FLAT | **date-gated only** — enforce-mode rejects on/after `blocked_after` `2027-01-31`; advisory before |
| `unsupported` (<5.0) | `[?, 5.0.0)` | none | advisory only — never an ingress blocker by itself |
| `unclassified` | unknown library / unparseable version | none | never blocked; open-bounds sentinel, never matches a parseable version |

Capability ids are canonical (`CAP_*` constants); per-band sets reference only
canonical ids. The band table is ordered newest → oldest and the first inclusive
match wins. `BLOCKED_AFTER_DATE` (`2027-01-31`) is the single fail-closed date:
**enforcement is by date, never by band alone**, and the Gate H validator fails
the build if that date ever moves into the past or a served band turns into a
premature blocker. Nothing here is a promise about a specific SDK build — bands
are advisory policy data consumed by operators and by the advisory ingress seam.

### Ingress consultation (staged, default OFF)

When `AETHER_SDK_VERSION_COMPAT_ENABLED` is ON, `/v1/batch` (canonical spine)
classifies each event's `context.library.version` against the band table and
attaches an **advisory tier label** `normalized["sdk_tier"]` (additive metadata
only, never a rejection by itself — this happens in every mode; `mode` does not
gate the label). `mode` gates **enforcement**:

* in `mode` = `enforce`, ingestion additionally REJECTS events whose SDK band is
  blocked-after-date AND whose date has arrived, with reason
  `sdk_version_blocked:<band>:<label>` (`sdk_version_ingress_blocked`);
* `off`/`shadow`/`warn` never reject (advisory attach only). Both the default-OFF
  flag and the far-out `blocked_after` date make all of this inert in the
  default tree.

Missing/unknown library, unparseable version, or unrecognized library name
resolves to `unclassified` and is never blocked. Known library-name recognition
is advisory (substring set in the module); version does the real classification.

### Capability manifest

`GET /v1/config/sdk/versions` (`services/sdk_config/routes.py`) serves
`tiers_payload()`: `schema_version`, `enabled`, `mode`,
`blocked_after_date`, the full tier table (id / status / label / min / max /
`deprecated_after` / `blocked_after` / capabilities / note), and the
`unclassified` sentinel. It is static, non-secret policy data whose read never
depends on the flag.

## 5. Gate conformance (repo-doctor)

Both gates are real, fail-closed repo-doctor validators dispatched from the
`repo_doctor.py` static-gate tail and locked by
`tests/unit/test_repo_doctor_cli.py`:

* `scripts/validate_kyber_ops_surface.py` (Gate G) fails if any of the seven
  facets loses its mounted, operator-only surface (de-mount, unregated Kyber
  route, or dropped health/versions route).
* `scripts/validate_sdk_compat_tiers.py` (Gate H) fails if the tier table
  regresses (served band date-blocked early, non-canonical capability, flat band
  claiming Envelope-B, `BLOCKED_AFTER_DATE` arrived, or a WS-E flag missing from
  settings / env examples / default-OFF).

## 6. Module map

| Concern | Module |
|---|---|
| Funnel + trace ledger | `Backend Architecture/aether-backend/services/ingestion/ingestion_observability.py` |
| Version-band model | `Backend Architecture/aether-backend/services/ingestion/sdk_version_tiers.py` |
| Operator observability router | `Backend Architecture/aether-backend/services/ingestion/observability_routes.py` |
| Replay router | `Backend Architecture/aether-backend/services/ingestion/replay_routes.py` |
| Ingestion spine recording seams | `Backend Architecture/aether-backend/services/ingestion/batch.py` |
| Worker recording seams (NORMALIZED / PROJECTIONS) | `Backend Architecture/aether-backend/services/ingestion/workers.py` |
| Pipeline health route | `Backend Architecture/aether-backend/services/gateway/routes.py` |
| Capability-manifest route | `Backend Architecture/aether-backend/services/sdk_config/routes.py` |
| Flags | `Backend Architecture/aether-backend/config/settings.py` · `.env.example` · `.env.production.example` |
| Gate validators | `scripts/validate_kyber_ops_surface.py` · `scripts/validate_sdk_compat_tiers.py` |
