---
title: Backend Interpretation (WS-D) Architecture
slug: architecture/backend-interpretation-ws-d
section: architecture
visibility: I
audience: [architect, dev-senior, ai]
status: experimental
canonical_owner: platform@aether
estimated_read_minutes: 20
toc_depth: 4
---

# Backend Interpretation (WS-D) Architecture

WS-D is the *backend-interpretation* slice of the SDK + Universal Ingestion
Alignment blueprint (workstream D of the PR #609 lane series). It makes the
backend's interpretation of ingress evidence first-class: typed relationships
with evidence lineage, an episode engine, a durable outcome-truth store,
Section-25 evidence dedupe, Silver-boundary temporal envelopes, first-class
correlation, exact-decimal Silver money, and derived-truth mutation governance.

The scope is fixed to gap rows **7 / 8 / 9 / 22 / 24 / 26 / 31** and Invariants
**#7 / #11 / #12 / #13 / #14** of the
`docs/productization/sdk-universal-ingestion-alignment/REPO_TRUTH_AND_GAP_MATRIX.md`.
Execution-state row 658 (`EXECUTION_STATE.md`) names this lane.

## 1. Guiding rules

1. **Every behavior-changing mechanism is gated behind a NEW default-OFF
   settings flag** (`BackendInterpretationConfig`). With all seven flags OFF the
   package and its wiring are inert — no production ingestion / Silver / graph
   path is reachable, and runtime output is byte-for-byte what the base branch
   produced. Enabling a flag is a deliberate operator decision, never a code
   default.
2. **Reuse, never redefine.** WS-D reuses canonical primitives
   (`EntityRef` / `EvidenceRef`, the OutcomeState finality ladder, the financial
   exact-money machinery, the existing mutation-gateway ladder) and declares no
   second copy of any of them.
3. **No competing system of record.** Episodes, outcome-truth rows and
   relationship facts are durable *projections/indexes* over canonical
   observations/outcomes (ADR-010); they never replace the system of record.
4. **Fail-isolated and import-defensive.** A WS-D helper that cannot reach its
   backing store or settings degrades to a typed absence / `None` — it never
   crashes the plane.
5. **Honest boundaries.** Where a change would require re-wiring a surface owned
   by another lane (Noesis execution capture, episode360 registry flip to
   `implemented`, projection-plane registration) WS-D delivers the ready seam and
   documents the follow-on instead of silently reaching across.

## 2. Flags

All flags live on `Settings.backend_interpretation`
(`Backend Architecture/aether-backend/config/settings.py`,
`BackendInterpretationConfig`) and are read through function-local helpers in
`shared/backend_interpretation/flags.py` (import-defensive; never drags the full
settings graph into a projector). Declared in `.env.example` and
`.env.production.example`.

| # | Flag env var | Settings attr | Blueprint item |
|---|---|---|---|
| 1 | `AETHER_BACKEND_RELATIONSHIP_FACT_ENABLED` | `relationship_fact_enabled` | Typed `RelationshipFact` + `evidence_refs` carry to the mutation ledger |
| 2 | `AETHER_BACKEND_EPISODE_ENGINE_ENABLED` | `episode_engine_enabled` | Canonical episode primitive + episode360 read surface |
| 3 | `AETHER_OUTCOME_TRUTH_STORE_ENABLED` | `outcome_truth_store_enabled` | Durable outcome truth store with evidence + model/policy lineage |
| 4 | `AETHER_EVIDENCE_DEDUPE_ENABLED` | `evidence_dedupe_enabled` | Section-25 evidence dedupe (one outcome, many evidence refs) |
| 5 | `AETHER_SILVER_TEMPORAL_ENVELOPE_ENABLED` | `silver_temporal_envelope_enabled` | Server temporal envelope reaches the Silver boundary |
| 6 | `AETHER_CORRELATION_FIRST_CLASS_ENABLED` | `correlation_first_class_enabled` | Correlation first-class (canonical registry, not opaque JSONB) |
| 7 | `AETHER_SILVER_EXACT_MONEY_ENABLED` | `silver_exact_money_enabled` | Silver money via exact Decimal; missing-never-0.0, currency never `'USD'` |

Derived-truth governance (item 8) has **no new flag**: it rides the pre-existing
`AETHER_MUTATION_GATEWAY_MODE` ladder (`off | shadow | enforce`, default `off`) —
no parallel governance knob, no production default flip.

## 3. Items

### Item 1 — Typed `RelationshipFact` + evidence carry (Invariant #14 / row 26)

Legacy graph edges carried bare vertex ids and an opaque properties blob; the
identity audit dropped per-signal evidence at promotion. WS-D introduces the
canonical typed relationship carrier `RelationshipFact`
(`shared/backend_interpretation/primitives.py`): canonical predicate +
direction, an explicit `resolution_method` (observed / source_asserted /
resolved / inferred / predicted / attributed / causally_supported / unresolved),
a `ValidityWindow` (active/expired/pending/superseded with the same
terminal-sink discipline as outcome finality), and first-class `evidence_refs`
that survive promotion.

- `facts.fact_from_assertion` bridges a promoted relationship-spine assertion
  into a `RelationshipFact`, choosing `resolution_method` honestly from the
  assertion's `claim_ceiling` (`derived` -> `inferred`, `observed` -> `observed`)
  and carrying every supporting observation id. **Kinds are required**: the graph
  promotion path carries bare vertex ids, so WS-D never guesses a kind — an
  omitted `subject_kind`/`object_kind` raises `ValueError` (fail-closed).
- `shared/relationship_spine/promotion.py` `project_assertion`: when the flag is
  ON, the assertion's `evidence_refs` and `correlation_id` are forwarded onto the
  `MutationIntent` so the mutation LEDGER record retains them (OFF keeps the
  pre-WS-D call byte-for-byte identical).
- `RelationshipFactStore` (`stores.py`) persists facts as JSON KV documents
  (`shared.store.get_store`, Redis/in-memory — the same durable seam as
  `ai_execution_facts`), tenant-scoped end to end.

### Item 2 — Episode engine + episode360 surface (gap rows 24/26/31)

`EpisodeRecord` (`primitives.py`) is the canonical episode primitive: a
time-bounded, subject-scoped, kind-tagged span that groups the observations and
outcomes telling one story (a support ticket, a user journey, an execution run).
It carries its own evidence lineage and the ids of the rows it spans — it
indexes canonical truth, never replaces it.

- `EpisodeEngine` (`services/measurement/episodes/engine.py`) keys an *open
  episode* by `(tenant, subject, kind)`: the first observation opens it, later
  observations append evidence/observation ids and widen `occurred_from`/`to`,
  and an explicit `close` (or an `episode.close` completion-kind observation)
  closes it. Episode ids are deterministic digests of `(tenant, subject, kind,
  genesis)` so a second episode for the same key after a close never overwrites
  the closed row. All writes are durable through `EpisodeStore`.
- `Episode360Provider` (`services/measurement/episodes/provider.py`) is the
  `episode360` intelligence-projection read surface (six sections: evidence /
  interactions / outcomes / state / summary / timeline), grounded in each
  episode's evidence lineage and fail-isolated like the outcome360 contract.
  Registry row `episode360` remains `in_flight`; the provider is NOT registered
  into `dependencies/projection_plane.py` until the row flips `implemented` in
  the same change that extends `IMPLEMENTED_PROJECTION_IDS`.
- Honest boundary (row 24): Noesis' execution capture writing
  `ai_execution_facts` directly (bypassing the gateway) is a WS-A/B-owned
  re-wiring. WS-D ships `EpisodeEngine` so a future row-24 capture can enqueue
  into it without a contract change.

### Item 3 — Durable outcome truth store (row 26/31)

The canonical outcome read (`outcome360`) returns `None` today because the
outcome repository adapter lands with the vertical slice. WS-D ships the durable
outcome-truth surface instead of leaving the hole:

- `OutcomeTruthRecord` (`primitives.py`) is the durable row WITH lineage the
  identity-style read drops: `claim_type`, `model_version`/`policy_version`,
  `source_event_ids` and every `evidence_refs` entry. Money is carried as
  `value_amount`/`value_currency` DECIMAL strings where `None` is a typed
  `value_state` absence (`missing`/`empty`/`zero`/`degraded`/`present`), never a
  silent `0.0`.
- `truth_recorder.record_from_silver_outcome` converts a projected Silver outcome
  row into the lineaged record (idempotent key `tenant:event_id:outcome_type`);
  `persist_outcome_truth` is the durable-write seam. Both are no-ops when the
  flag is OFF.
- `services/ingestion/workers.py` `silver_fact_projector`: when the flag is ON,
  every projected `silver_outcome_facts` row is mirrored into the truth store
  (best-effort; Bronze is durable and replay recovers missed rows — a recorder
  failure never fails the projection).
- `OutcomeTruthStoreReader` (`stores.py`) satisfies the
  `OutcomeStore` protocol (`services/measurement/outcome/provider.py`), so
  `outcome360` reads durable, lineage-carrying truth when the flag is ON and rows
  exist — and degrades to typed `missing`/`empty` exactly as before otherwise
  (OFF keeps `_measurement_outcome_store()` returning `None`).
- The recorder also registers the outcome's correlation family when present
  (item 6 composition).

### Item 4 — Section-25 evidence dedupe (row 9/26)

`shared/backend_interpretation/dedupe.py` implements the blueprint §25 rule: the
SAME real-world outcome observed through the browser SDK, a webhook and a
connector is ONE canonical outcome with THREE evidence refs — never three
outcomes and never duplicate evidence rows.

- `canonical_outcome_key` prefers the correlation family ids
  (`correlation_id` > `causation_id` > `parent_observation_id`) then falls back
  to a stable subject+type+occurred-day key; records too sparse to key are
  skipped.
- `default_fingerprint` is the *literal* identity of one underlying event: the
  same event id on the same channel collapses to ONE ref, while a different
  webhook id for the same outcome stays a DISTINCT ref (the §25 collapse we keep).
- `dedupe_evidence` merges a batch into `DedupeGroup`s. Pure function surface —
  the module has no side effects and is trivially testable. Honest boundary: flag
  gating is the caller's job and no production write path consumes the groups yet
  (WS-A/B evidence back-link seams are documented to reuse
  `canonical_outcome_key`).

### Item 5 — Silver temporal envelope (Invariant #11 / rows 7/22)

`services/ingestion/workers.py` `_apply_silver_temporal`: when
`AETHER_SILVER_TEMPORAL_ENVELOPE_ENABLED` is ON and the normalized Bronze payload
carries the server-built `temporal` block, its authoritative `occurred_at`
replaces the raw client `timestamp` on the projector envelope, and the full
temporal envelope is carried to the Silver edge. OFF is byte-for-byte unchanged
(the envelope object is returned untouched). This closes the row-7/22 gap where
Silver projectors re-read the raw client timestamp and silently discarded the
server's normalization.

### Item 6 — Correlation first-class (Invariant #12 / row 8)

Correlation was opaque (stored as JSONB, dropped at promotion). WS-D promotes it:

- `CorrelationRegistry` (`stores.py`) is the canonical, tenant-scoped,
  first-class index: one row per `(tenant, correlation_id)` family accumulating
  observation ids, evidence refs, causation links and source channels.
- `observe.register_correlation_from_observation` folds one normalized
  observation record into its family (returns `None` when the flag is OFF or the
  record carries no correlation id).
- `shared/relationship_spine/promotion.py` registers the promoted edge's
  correlation family on the promotion path (item 6) and forwards
  `correlation_id` onto the gateway intent (item 1); the outcome-truth recorder
  registers outcome correlation families (item 3). Registry writes are
  best-effort — a failure never fails the projection/promotion.

### Item 7 — Silver exact money (Invariant #13 / row 13)

`shared/backend_interpretation/money.py` reuses the financial-normalization exact
machinery (`services.value.models.to_decimal_string`) — it does NOT re-implement
money and does NOT build a second money type. Under
`AETHER_SILVER_EXACT_MONEY_ENABLED`:

- the revenue and outcome Silver projectors stop collapsing a missing amount to
  `0.0` and a missing currency to `'USD'`: a missing/unparseable amount is a
  typed absence (`None`), a present amount is recorded as an exact decimal
  string, and the currency is the source's verbatim (never defaulted);
- the additive canonical exact-money columns are emitted (`amount_exact` /
  `currency_exact` on `silver_revenue_facts`, `value_amount_exact` /
  `value_currency_exact` on `silver_outcome_facts`).

OFF (default) is byte-for-byte the historical behavior, and the legacy NOT NULL
money columns keep pre-WS-D semantics.

### Item 8 — Derived-truth mutation governance (row 658)

`shared/backend_interpretation/governance.py` implements the blueprint rule that
DERIVED truth may only be mutated by an authorized derivation mechanism and every
derived write MUST carry its derivation lineage (`claim_type="derived"`, a
`model_version` and/or policy ref, `>= 1` evidence ref, a `source_event_id` and a
`reason_code`). It rides the pre-existing `AETHER_MUTATION_GATEWAY_MODE` ladder:

- `off` — `assess_derived_write` returns `permit=True` with `mode="off"` and
  records no violations (byte parity);
- `shadow` — violations are computed and reported but the caller proceeds;
- `enforce` — a lineage-incomplete derived write is DENIED (`permit=False`).

`enrich_derived_intent` maps a WS-D carrier's lineage onto the existing
`shared.graph.mutation_gateway.MutationIntent` surface so a governed derived
write records the same lineage the gateway already understands. The
outcome-truth recorder (item 3) routes its writes through this assessment.

## 4. Runtime parity guarantee

With all seven flags OFF and `AETHER_MUTATION_GATEWAY_MODE=off` (the defaults):

- projectors emit byte-for-byte the rows the base branch emitted (verified by
  `test_revenue_money_off_is_byte_parity`, `test_silver_temporal_off_preserves_raw_timestamp`,
  etc.);
- `_measurement_outcome_store()` returns `None` and outcome360 degrades exactly
  as before;
- promotion/ingestion paths keep their pre-WS-D calls identical;
- the new stores are safe to construct but no write path reaches them.

None of the new helpers are reachable from any production ingestion / Silver /
graph path while the flags are OFF.

## 5. Durable storage

The four stores (`RelationshipFactStore`, `EpisodeStore`, `OutcomeTruthStore`,
`CorrelationRegistry`) wrap named `shared.store.get_store(...)` KV stores — the
same Redis/in-memory durable seam that backs `ai_execution_facts`/agent tasks.
Rows are JSON documents keyed by `tenant_id:record_id` with a top-level
`tenant_id` so `DurableStore.find(tenant_id=...)` stays tenant-scoped end to end.
No new Alembic table is required for the KV stores. The ONLY schema change is the
item-7 migration `alembic/versions/20260906_wsd_silver_exact_money.py` (additive
columns; see below).

## 6. Schema migration

`20260906_wsd_silver_exact_money` (item 7) is an additive WIDENING only:

- `silver_revenue_facts.amount`/`.currency`: `DROP NOT NULL` (+ currency
  `DROP DEFAULT`) on PostgreSQL so a typed money absence can be stored; value
  semantics unchanged while the flag is OFF because the default-OFF projector
  always supplies a value. SQLite cannot `DROP NOT NULL` via ALTER and skips the
  widening (dev/test only; production is PostgreSQL).
- Adds `amount_exact NUMERIC(38,18)` / `currency_exact TEXT` on
  `silver_revenue_facts` and `value_amount_exact NUMERIC(38,18)` /
  `value_currency_exact TEXT` on `silver_outcome_facts`
  (financial-normalization `NUMERIC(38,18)` convention).

`down_revision` is the single lane head `20260906_merge_data_exchange_head`.
COORDINATOR SHARED-SURFACE note: when combined with sibling WS lanes that each
add a migration off that head, a NEW tuple-merge revision must be created with
`down_revision = (<this>, <sibling>, ...)` exactly like
`20260906_merge_data_exchange_head`.

## 7. Flip sequences

Nothing is enabled by default. To adopt a mechanism, set its flag (and for item
8 the gateway mode) in the deployment environment:

1. **Item 5** (temporal) first — it only makes projectors honor the server
   envelope already present in Bronze payloads.
2. **Item 7** (exact money) after its migration is applied; flip together with
   financial-normalization consumers that read the `*_exact` columns.
3. **Items 1/3/6** can be enabled independently once their KV stores are
   reachable; writes are best-effort/idempotent and reads degrade to typed
   absence.
4. **Item 4** is enabled when a write seam consumes `dedupe_evidence`
   (WS-A/B back-link follow-on).
5. **Item 8**: advance the ladder `off -> shadow -> enforce`; never jump to
   `enforce` before `shadow` output has been reviewed.

## 8. File inventory

New shared package `Backend Architecture/aether-backend/shared/backend_interpretation/`:
`primitives.py`, `dedupe.py`, `stores.py`, `governance.py`, `flags.py`,
`observe.py`, `money.py`, `facts.py`.

New domain surface `Backend Architecture/aether-backend/services/measurement/`:
`episodes/engine.py`, `episodes/provider.py`; `outcome/truth_recorder.py`.

Modified: `services/ingestion/workers.py` (items 3/5),
`services/measurement/outcome/provider.py` (item 3 read),
`services/silver/projectors/revenue_projector.py` + `outcome_projector.py`
(item 7), `shared/relationship_spine/promotion.py` (items 1/6),
`config/settings.py` + `.env.example` + `.env.production.example`
(`BackendInterpretationConfig` + flags), and the item-7 Alembic migration.

Tests: `tests/unit/backend_interpretation/` (`test_core.py`, `test_episodes.py`,
`test_silver_wsd.py`, `conftest.py`).

## 9. Tests and honest verification boundaries

- **Item 1**: typed-fields/resolution + never-guesses-kind (`ValueError`).
- **Item 2**: engine open/append/close + new-episode-after-close,
  completion-hint close, episode360 provider section rendering, empty store is
  typed `empty`.
- **Item 3**: recorder OFF no-op, ON retains evidence + model/policy lineage,
  outcome360 reads durable truth.
- **Item 4**: one-outcome-three-evidence-refs, literal duplicate collapse,
  subject+type+day fallback, too-sparse skip.
- **Item 5**: OFF preserves raw timestamp, ON uses server `occurred_at`, no
  payload temporal -> unchanged.
- **Item 6**: flag-gating (OFF no-op) + correlation family merge.
- **Item 7**: OFF byte parity, ON exact-never-fabricates for revenue + outcome.
- **Item 8**: off/shadow/enforce decision matrix + lineaged write passes +
  `enrich_derived_intent` lineage mapping.

Verified boundaries: item 2 provider is tested directly against an injected
store — it is NOT live in the projection plane (episode360 row `in_flight`).
Item 4 has no production write seam yet. Item 7's migration widening is not
exercised on SQLite in CI. All mechanisms are flag-gated OFF, so no production
default path is affected by any of these boundaries.

## 10. Cross-lane coordination

- `services/ingestion/workers.py` is the envelope seam also touched by WS-C
  (correlation/observation envelope). WS-D changes there are additive and
  compose; a reviewer from the envelope-owning lane should confirm the combined
  seam.
- `config/settings.py` + `.env.example`/`.env.production.example` receive the
  additive `BackendInterpretationConfig` block and seven flag lines.
- The migration `down_revision` is a single lane head; combining with sibling WS
  lanes requires a tuple-merge revision (see section 6).
- Item 7 deliberately reuses `services.value.models.to_decimal_string` from
  `feat/financial-normalization` rather than building a second money type.
