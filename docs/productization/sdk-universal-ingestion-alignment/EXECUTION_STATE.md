---
title: Execution State — SDK + Universal Ingestion Alignment
slug: productization/sdk-universal-ingestion-alignment/execution-state
section: operations
visibility: I
audience: [architect, ops, exec]
status: beta
since_version: "8.12.0"
canonical_owner: platform@aether
---

# Execution State

> **Delivery model (supersedes per-slice merges):** all WS-A…E implementation
> slices are delivered as **stacked commits on one branch,
> `feat/sdk-universal-ingestion`**, and land as **one consolidated program PR**
> (no per-slice PRs/merges). The canonical gate is run **once at the full-program
> tip**, not per slice. Slice rows below record their commit + content; the
> "Branch off …" lines describe the base each slice was authored on before the
> stack consolidated.
>
> **Gate policy (user directive):** do not start `make ci-check` /
> `repo-doctor` / `docs_drift` until the entire WS-A…E program build is
> completely over and done with; the single final gate runs then.

## Phase 0 — convergence bedrock

Convergence bedrock (Phase 0 base = `bfea2e93`, `origin/main` head at landing,
which carried Communication360 #596 on top of the 360 program #593).
Make the canonical architecture authoritative *and enforced* without yet building
the big missing pieces. This page + `TARGET_ARCHITECTURE.md` +
`REPO_TRUTH_AND_GAP_MATRIX.md` are the governed home for the program.

| Workstream | Deliverable | Status |
|---|---|---|
| A — Canonical governed docs | `docs/productization/sdk-universal-ingestion-alignment/{TARGET_ARCHITECTURE,REPO_TRUTH_AND_GAP_MATRIX,EXECUTION_STATE}.md` (this directory) | ✅ implemented (this slice) |
| B — Resolve ADR-007 collision | Renumber `ADR-007-observation-only-execution-invariant.md` → `ADR-011-observation-only-execution-invariant.md`; fix ADR-008 + `DOCS_REVIEW_BACKLOG` links | ✅ implemented (this slice) |
| C — Deprecate legacy trees + orphans | Do-not-extend banners on `Data Ingestion Layer/README.md` + `Data Lake Architecture/README.md`; deprecated-orphans subsection in `Backend Architecture/README.md` | ✅ implemented (this slice) |
| D — First two CI gates | `scripts/validate_canonical_ingestion_trees.py` (canonical-tree ownership) + `scripts/validate_sdk_import_boundary.py` (SDK thinness), allowlists, ownership category `legacy_ingestion_tree_mutation`, unit tests | ✅ implemented (this slice) |
| Integration + final gate | `make repo-doctor-fix` (regenerate `docs/_generated/**` once), four commits in A→B→C→D order, `make ci-check` = 0, `git status --short` empty, `docs_drift.py --strict` clean | ⏳ integrator-owned |

### Definitions of done (Phase 0)

- `make ci-check` exits **0** — the only valid completion gate.
- `git status --short` is empty; every generated diff (`docs/_generated/**`,
  `docs/REPO-INDEX.md`, `docs/AUTOMATION.md`) is committed, never hand-edited.
- `python scripts/docs_drift.py --strict` is clean (the ADR-011 move is drift-safe:
  its `source_files`/`last_synced_commit` are untouched and `4e6fdad` is an
  ancestor of `origin/main`).
- The four tickets' changes are confined to their owned files; no stray edits.
- The PR carries full deliverable context (A→D, gate semantics, ADR-011 blast
  radius, deprecation inventory, why no deletion in Phase 0, and the
  out-of-scope note that `docs/plans/RISK_FRAUD_360_PHASES.md` is not on
  `origin/main`).

## WS-A1 — blueprint canonicalization + spec recovery

Merged to `origin/main` via PR #600 (`b4fc4d18`), squash of slice branch
`feat/sdk-univ-ws-a1` off `d379a9d2` (= `origin/main` head after the Phase 0
squash-merge, PR #599).
Commit the controlling 34-section alignment blueprint in-repo and make the
alignment docs authoritative against it, so executors steer against committed
content — not session memory or an external paste.

| Workstream item | Deliverable | Status |
|---|---|---|
| Commit verbatim blueprint | `docs/blueprints/sdk-universal-ingestion-alignment.md` — verbatim recovery of the 34-section blueprint (sections 0–34, sections 0–1 headers through the section-34 final-architecture diagram), frontmatter-governed (`canonical_owner: platform@aether`, authored, not generated); the section-34 tail truncation is documented in a clearly-labelled provenance note, not reconstructed | ✅ implemented (this slice) |
| Point the alignment docs at it | `TARGET_ARCHITECTURE.md` names the in-repo blueprint as the controlling artifact (was: external paste) | ✅ implemented (this slice) |
| Spec recovery (WS-A…E working decomposition) | The 2026-09-04 parallel recovery pass produced per-workstream implementation tickets carrying the authoritative spec detail (field-trust taxonomy, Level A/B/C, Gates G/H, missing-vocabulary enumeration, file-level line anchors). Downstream WS slices are executed against the committed blueprint + this ledger + the curated `TARGET_ARCHITECTURE.md`/`REPO_TRUTH_AND_GAP_MATRIX.md`; file-level anchors are re-verified at each slice's start | ✅ recorded |

### Definition of done (WS-A1)

- `docs/blueprints/sdk-universal-ingestion-alignment.md` committed, frontmatter-valid.
- `TARGET_ARCHITECTURE.md` and this ledger reference it as the controlling artifact.
- Canonical gate green: `make ci-check` = 0, `git status --short` empty,
  `docs_drift.py --strict` clean.

## WS-A2 — field-trust taxonomy in the Contract Spine

Authored as slice branch `feat/sdk-univ-ws-a2` off `b4fc4d18` (= `origin/main`
head after the WS-A1 squash-merge, PR #600); under the stacked model this content
is carried on `feat/sdk-universal-ingestion` as commits `571de852` … `9b77cdda`
(base `584fda74` = #601), delivered in the consolidated program PR (supersedes
the closed un-merged PR #602).
Put per-field trust/authority metadata on the SDK-facing event families in the
Contract Spine (additive `schemaVersion` 2.1.0), emit the per-field maps to the
TS + Python twins, and enforce them with a parity gate — the first real spine
mutation of the program. Descriptive in WS-A2; boundary enforcement is WS-A3.

| Workstream item | Deliverable | Status |
|---|---|---|
| Spine field-trust block | `event-registry.json`: `schemaVersion` **2.1.0** + `fieldTrustSchemaVersion` `1.0.0`, `trustClasses` (canonical rank-ordered 10, verbatim from the committed blueprint), `fieldTrustDefaults`, `_registryNotes.field_trust` (incl. the SDK-assertable boundary is a class SET, not a linear cut — resolved WS-A3) | ✅ implemented (this slice) |
| Per-event content | `fieldTrust.fields` on **117 events** across the 14 SDK-facing families (core 7 + journey/reward/wallet, identity_lc/identity/consent, commerce/ecommerce, b2b/friction, interaction/exposure, x402): app-authored events → `userId: CLIENT_HINT` + `properties: SOURCE_ASSERTED`; pure-observation events stay OBSERVED (no block); external-source leaves (`properties.address/txHash/contract/external_ref/quoteId`) → SOURCE_REFERENCE, each file:line evidenced | ✅ implemented (this slice) |
| Generator emission | `generate_contracts.py` `validate_field_trust()` (structural rules) + emits `TRUST_CLASS_ORDER`/`TrustClass`/`FieldTrustSpec`/`EVENT_FIELD_TRUST` to the TS twin and `TRUST_CLASS_ORDER`/`EVENT_FIELD_TRUST` to the Python twin | ✅ implemented (this slice) |
| Parity gate | `scripts/validate_field_trust_parity.py` (regenerate-and-diff over both twins + structural validation), wired into `scripts/repo_doctor.py` → `make ci-check`; closes the `generate_contracts.py` CI-coverage gap | ✅ implemented (this slice) |
| Ownership map | New `event_field_trust_schema` category in `repo_consistency_ownership.json` + mirrored `REPO_CONSISTENCY_OWNERSHIP.md` row | ✅ implemented (this slice) |
| Tests | `tests/unit/test_validate_field_trust_parity.py` + wiring test in `test_repo_doctor_cli.py`; `test_commerce_parity.py::test_registry_shape` top-level-key pin extended for the additive WS-A2 keys | ✅ implemented (this slice) |
| Integration + final gate | `make repo-doctor-fix` **70/0** (wrote the synced-doc reindex — `REPO-INDEX.md` `scripts` 184→185 / `tests` 541→542 once the two new files were tracked); 11 source-linked docs genuinely reviewed against the additive change and restamped (also healing the pre-existing `AWS-DEPLOYMENT.md` staleness from #598 in-band); **`make ci-check` 73/0** at HEAD `424a761a` (pre-consolidation tree; the consolidated tip `9b77cdda` differs only by rebase shas + dropping the AWS-DEPLOYMENT opportunistic restamp — gate-neutral, docs-only), `git status --short` empty, `docs_drift.py --strict` exit 0 | ✅ implemented (this slice, stacked) |

### Definition of done (WS-A2)

- `make ci-check` exits **0** — the only valid completion gate.
- `git status --short` empty; regenerated twins + synced docs committed, never
  hand-edited.
- `python scripts/validate_field_trust_parity.py` green (117 events carry
  `fieldTrust.fields`; TS + Python twins match the registry) and
  `python scripts/generate_contracts.py --check` idempotent.
- `validate_consistency_ownership.py` green for the new `event_field_trust_schema`
  category.
- No validators weakened; no new ADR.

## WS-A3 — minimum-trust + Level A/B/C + SDK trust boundary

Stacked on `feat/sdk-universal-ingestion` at `3e559da9` (base `584fda74` = #601),
authored on top of the WS-A2 stack (`571de852`…`9b77cdda`), delivered in the
consolidated program PR. Canonical gate deferred to the full-program tip per the
gate-policy directive; the generator run that validates the new registry and
regenerates the twins (exit 0) is the recorded build evidence.
The spine declares a per-event semantic release level (A/B/C) and an SDK
emittability boundary; the static gate asserts public-SDK emittable events never
declare Level C and never carry a field-trust class the public SDK cannot assert
(SDK ≤ CLIENT_HINT; RESOLVED/SERVER_STAMPED+ are backend-only). Runtime
enforcement at the ingestion boundary is deliberately **deferred to WS-B's
universal gateway** (flag-gated OFF there) so the still-un-runnable green tree is
not risked — WS-A3 ships the spine + generator + static boundary validation only.

| Workstream item | Deliverable | Status |
|---|---|---|
| Spine semantic-level + boundary block | `event-registry.json`: `schemaVersion` **2.2.0** + `semanticLevelSchemaVersion` `1.0.0` + `semanticLevels` catalog {A primitive, B typed source, C derived Aether state}, + `sdkBoundarySchemaVersion` `1.0.0` + `sdkBoundary` {`publicSdk`: assertableTrustClasses = class SET `OBSERVED/SOURCE_ASSERTED/SOURCE_REFERENCE/CLIENT_HINT` + emittableSemanticLevels `A,B`; `aetherInternal`: full 10-class rank + `A,B,C`}; `_registryNotes` gained `semantic_levels` + `sdk_boundary`, and the WS-A2 `field_trust` note tail rewritten to the A3-resolved SDK-boundary wording (class set, not a rank cut) | ✅ implemented (this slice) |
| Per-event classification | every event carries `semanticLevel` A/B/C + boolean `sdkEmitable`: **A = 17** (track,page,screen,heartbeat,error,performance,experiment,identify,consent,interaction_observed,ui_interaction_observed,active_interval_observed,api_request_observed,action_attempted/succeeded/failed/cancelled), **B = 371**, **C = 15** (journey_completed,deferred_attribution_resolved,app_install_attributed + stablecoin/derivatives/interop reconciliation_run_completed/variance_detected/variance_resolved + stablecoin_flow_aggregate_materialized + derivatives pnl/exposure_snapshot_materialized); **sdkEmitable = 153**; zero sdkEmitable-and-C; the four F-family non-emittable events = app_install_attributed,deferred_attribution_resolved,journey_completed,reward_action_queued | ✅ implemented (this slice) |
| Generator self-gating validation | `generate_contracts.py` `_validate_semantic_boundary()` (runs first inside `validate_field_trust`): per-event semanticLevel ∈ A/B/C, sdkEmitable is bool, sdkEmitable ⇒ level ∈ publicSdk.emittableSemanticLevels, publicSdk classes known + none ≥ SERVER_STAMPED index, "C" never a public emit level, aetherInternal.assertableTrustClasses == full 10-rank, sdkEmitable fieldTrust trustClasses ∈ public-SDK set | ✅ implemented (this slice) |
| Twin emission | `_semantic_boundary_ts_block` + `_semantic_boundary_py_block`: TS `SEMANTIC_LEVEL_ORDER`/`SemanticLevel`/`EVENT_SEMANTIC_LEVEL` (403)/`SDK_ASSERTABLE_TRUST_CLASSES`/`SDK_EMITTABLE_SEMANTIC_LEVELS`/`SDK_EMITTABLE_EVENT_TYPES` (153) and the Python mirrors (frozenset, 153 confirmed) | ✅ implemented (this slice) |
| Parity gate | `validate_field_trust_parity.py` docstring + OK line extended (reports `n sdkEmitable` + level {A,B,C} counts); regenerate-and-diff now covers the semantic-boundary section of both twins | ✅ implemented (this slice) |
| Ownership map | `repo_consistency_ownership.json` `event_field_trust_schema` category name + `test_semantic_boundary.py` required-command + remediation extended to cover the semantic-level/trust-boundary declarations and `_validate_semantic_boundary`; mirrored `REPO_CONSISTENCY_OWNERSHIP.md` row updated | ✅ implemented (this slice) |
| Tests | new `tests/unit/test_semantic_boundary.py` (13 tests: pre-2.2 no-op, valid-boundary pass, missing level / C-as-emittable / unknown-level / non-bool-emittable / SERVER_STAMPED-in-SDK-set / C-as-public-emit-level / internal-classes≠full-rank failures, sdkEmitable-declaring-backend-only-field fails, sdkEmitable-declaring-assertable-field passes, live-registry 2.2.0 boundary pass) + `test_commerce_parity.py::test_registry_shape` top-level-key pin extended for the four additive WS-A3 keys | ✅ implemented (this slice) |
| Build evidence | generator exit 0 on the 2.2.0 registry (validation passed + both twins regenerated); canonical `make ci-check` deferred to the full-program tip (user gate policy) | ✅ implemented (this slice, stacked) |

### Definition of done (WS-A3)

- `event-registry.json` is 2.2.0 and passes `_validate_semantic_boundary` with
  zero sdkEmitable-and-C and zero sdkEmitable event declaring a non-public-SDK
  field-trust class.
- TS + Python twins carry the semantic-boundary section and match a fresh
  regeneration.
- Canonical gate green at the full-program tip: `make ci-check` = 0,
  `git status --short` empty, `docs_drift.py --strict` clean.
- No validators weakened; no new ADR; runtime enforcement deferred to WS-B.

## WS-A4 — missing vocabularies (grounded privacy DSR family; enrichment/economic notes)

Stacked on `feat/sdk-universal-ingestion` at `f5048446` (base = the WS-A3 tip
`4ba07daf`), delivered in the consolidated program PR. Canonical gate deferred to
the full-program tip per the gate-policy directive; the two generator runs that
validate the 403-event registry and regenerate the twins/tables (both exit 0) are
the recorded build evidence.
WS-A4's reserved scope ("missing vocabularies" per the blueprint §4: `enrichment`/
`economic`/`privacy` (+ blueprint-listed)) was under-determined — no committed
enumeration exists. Recon across the tree established the ground truth, and the
user chose **"add a conservative grounded set."** Resolution per vocabulary:

| Vocabulary | Decision | Evidence |
|---|---|---|
| `enrichment` | **NO family.** Inline field-stamping only — no emitter, no run lifecycle, no SDK surface; `context_enricher.py` augments an event already owned by its source family. Recorded here, not invented as a family | blueprint §4 treats enrichment as a *registry* (pre-observation field stamps), not an event family |
| `economic` | **NO new events.** Already governed across `derivatives` (41) / `stablecoin` (30) / `interop` (39) / commerce / x402 / agent-trade; a parallel "economic" family would duplicate silver vocabulary | family census + `test_event_registry_economic_domains.py` subset pin |
| `privacy` | **5-event DSR lifecycle family ADDED** (below) — grounded in real mounted compliance code | `services/consent/routes.py`, `erasure_jobs.py`, `dsr_propagation/models.py`, `security/retention.py` |

Added to `event-registry.json` (schemaVersion stays **2.2.0** — additive events
only, no new top-level key; contractVersion stays 8.12.0): **403 events / 25
families**, A = 17, **B = 371**, C = 15, sdkEmitable = 153.

- `data_subject_request_received` / `data_subject_request_queued` /
  `data_subject_request_denied` / `erasure_completed` / `erasure_failed` —
  family `privacy`, `semanticLevel` B, `sdkEmitable` false, `privacyClass`
  governance, `retentionClass` permanent, `requiredPurposes` [],
  `introducedVersion` 8.12.0. Grounded in the consent DSR service
  (`services/consent/routes.py:307-369`, status `pending→queued`,
  publishes `aether.consent.dsr`), the durable-erasure propagator
  (`services/consent/erasure_jobs.py:280-586`, statuses `completed`/`failed`),
  `services/dsr_propagation/models.py` (DSR_TYPES + per-step statuses), and the
  retention/data-request denied path (`services/security/retention.py:138`).
- `projector-ownership-registry.json` `noProjection`: `privacy` =
  `no_projection` ("Privacy DSR/compliance lifecycle events are control-plane
  state owned by the consent/DSR authority, not Silver analytics facts") —
  mirrors the `consent` no_projection precedent. No dispatcher projector, by
  design.

| Workstream item | Deliverable | Status |
|---|---|---|
| Spine vocabularies | `privacy` family (5 events) added with full WS-A3 metadata (level B / non-emittable / governance / permanent / no-purpose); enrichment + economic documented as no-add above | ✅ implemented (this slice) |
| Projector ownership | `privacy` noProjection entry (status `no_projection`) + regenerated `generated_ownership.py` + `projector-ownership-table.md` row | ✅ implemented (this slice) |
| Twins/tables | `generate_contracts.py` exit 0 (403 events; regenerated `events.ts`, `generated_registry.py`, `generated-consent-map.ts`, `event-registry-table.md` — header now "(403 types, contract v8.12.0)"); `generate_platform_contracts.py` exit 0 (temporal surfaces roll to **25 families**; projector-ownership-table gained the privacy row) | ✅ implemented (this slice) |
| Native parity co-edits | 5 privacy types hand-added to iOS `AetherEventType` enum + `eventConsentPurpose` and Android `EVENT_CONSENT_PURPOSE`, purpose `"analytics"` (the generator's empty-`requiredPurposes` default — same value the `consent` event maps to). Inline mirror-parse self-check: iOS enum / iOS purpose / Android purpose each = 403 = registry, bidirectional, zero extras | ✅ implemented (this slice) |
| Authored doc count sync | `CANONICAL_EVENT_MODEL.md` (398/24 → 403/25), `REPO_TRUTH_AND_GAP_MATRIX.md` row-18 (398 → 403), `EXECUTION_STATE.md` WS-A3 pins (B 366 → 371, `EVENT_SEMANTIC_LEVEL` 398 → 403) | ✅ implemented (this slice) |
| Source-linked docs review | 7 docs declaring `source_files: event-registry.json` reviewed: CANONICAL_EVENT_MODEL (global-count edit, above); SDK-COMMERCE-BRIDGES, COMMS_TRUTH_MATRIX, FIRST_RELEASE_INTELLIGENCE_TELEMETRY_OPERATIONS, DERIVATIVES/INTEROP/STABLECOIN_EVENT_REGISTRY — content **unaffected** by a new non-economic `privacy` family (per-domain counts unchanged). Pre-existing prose inaccuracies surfaced during review — `FIRST_RELEASE_INTELLIGENCE_TELEMETRY_OPERATIONS.md` "267 events, 21 families", `COMMS_TRUTH_MATRIX.md` "comms family has 15 events" — are **WS-A7** un-stale scope (recorded here, not opportunistically rewritten). `docs_drift.py --update` restamp deferred to the full-program tip per the gate-policy directive (WS-A3 precedent) | ✅ reviewed (restamp deferred) |

### Definition of done (WS-A4)

- `event-registry.json` = 403 events / 25 families (A=17, B=371, C=15,
  sdkEmitable=153), schemaVersion 2.2.0, boundary-valid by construction
  (B-level / non-emittable / empty-purpose with governance privacy + permanent
  retention).
- TS + Python + temporal twins/tables match a fresh regeneration of both
  generators (exit 0 recorded above).
- iOS/Android native event/consent surfaces mirror the full 403-type registry
  (bidirectional — inline parse confirmed).
- Canonical gate green at the full-program tip: `make ci-check` = 0,
  `git status --short` empty, `docs_drift.py --strict` clean.
- No validators weakened; no new ADR; enrichment + economic additions
  deliberately NOT invented (documented above).

## WS-A5 — Envelope B server-side: UniversalObservationEnvelope model + registry + adoption (flag)

Stacked on `feat/sdk-universal-ingestion` — feat content at `b1d89132`,
tests/ownership at `f8ec5d3e`, ledger close-out below (base = the WS-A4 tip
`0d0ce8cc`), delivered in the consolidated program PR. Canonical gate deferred to the
full-program tip per the gate-policy directive; the build-time self-checks below are the
recorded evidence.
WS-A5 ships the **model, not the enforcement** (the blueprint's PR-2 note: "create
backend canonical representation. Do not break BaseEvent."). Scope boundary, applied
throughout: `BaseEvent` stays the public Envelope A; `UniversalObservationEnvelope` is
server-built by the SDK adapter after validation; structural validation happens at
build time, source-trust/consent/idempotency/lineage stay the WS-B gateway's job.

**The triad (bound in lock-step by `tests/contracts/test_observation_envelope_parity.py`):**

| Surface | File | Role |
|---|---|---|
| Canonical field registry | `packages/shared/contracts/observation-envelope-registry.json` (schemaVersion 1.0.0) | §3 block tree → machine-readable: blocks + field requiredness + vocabularies + `naming_resolutions` (source_native_id/subjects[]/signature_status/adapter/occurred_at-vs-source_time/trust-vocab) + `passthrough_blocks` note |
| Runtime model | `Backend Architecture/aether-backend/shared/observation/envelope.py` (+ `__init__.py` barrel) | pydantic v2, every class `extra="forbid"`; 11 model classes; curated vocab tuples (source/identifier/credential) + `TRUST_CLASSES` frozenset asserted == `generated_registry.TRUST_CLASS_ORDER`; `to_bronze_additive()` JSON-safe dump |
| Passive TS twin | `packages/shared/observation-envelope.ts` (+ `index.ts` barrel export) | Contract mirror; explicitly NOT a client emitter (no builder/emit) — adapters build Envelope B inside Aether |

**Flag-gated adoption (default OFF, `AETHER_OBSERVATION_ENVELOPE_ENABLED`):**

- `ObservationEnvelopeConfig` frozen dataclass + `settings.observation_envelope` root field
  (`Backend Architecture/aether-backend/config/settings.py`); operator-facing flag block in
  `.env.production.example` next to the Ingestion V2 flags.
- SDK mapping `Backend Architecture/aether-backend/services/ingestion/observation_envelope.py`:
  normalized SDK dict → envelope; subject `trust_class` derived from `EVENT_FIELD_TRUST`
  (WS-A2) — `user_id` → CLIENT_HINT (fallback), `anonymous_id` → OBSERVED — never above the
  WS-A3 public-SDK boundary; temporal enforcement stamp (sequence coerced to the envelope's
  string `sequence`, `utc_offset` derived); correlation from EventContext; payload = properties.
- `batch.py` V1 accepted path (after `server_context` injection, before the `Event` bus
  object): when the flag is ON, builds + attaches `normalized["observation_envelope"]`
  additively (the shared dict reaches both the bus payload and durable Bronze); any mapping
  failure warn-degrades with a `ingestion_observation_envelope_*` meter — the flag can never
  take ingestion down. Flat-dict consumption unchanged until WS-B.
- Ownership: new `observation_envelope` change category in `repo_consistency_ownership.json`
  + `REPO_CONSISTENCY_OWNERSHIP.md` row (registry ↔ runtime model ↔ TS twin lock-step).

| Workstream item | Deliverable | Status |
|---|---|---|
| Field registry | `observation-envelope-registry.json` with §3 blocks, requiredness, vocabularies, naming resolutions, passthrough-block note (acquisition/application/surface/device/network/payload fields NOT re-declared — A-side EventContext/AcquisitionEvidence owns that shape) | ✅ implemented (this slice) |
| Runtime model | `shared/observation/envelope.py`: ObservationBlock/TenancyBlock/SourceBlock/SubjectRef/TemporalBlock/CorrelationBlock/PrivacyBlock/ProvenanceBlock/QualityBlock/LineageBlock + UniversalObservationEnvelope, extra=forbid, curated-vocab validators, `to_bronze_additive` | ✅ implemented (this slice) |
| Passive TS twin + barrel | `observation-envelope.ts` (mirror interfaces + SOURCE_TYPES/IDENTIFIER_TYPES/CREDENTIAL_CLASSES/TRUST_CLASSES `as const` + schema-version const), exported from `packages/shared/index.ts` | ✅ implemented (this slice) |
| Flag-gated adoption | `ObservationEnvelopeConfig` (OFF), mapping module, batch V1 attach point, `.env.production.example` block | ✅ implemented (this slice) |
| Parity + unit coverage | `tests/contracts/test_observation_envelope_parity.py` (registry↔TS↔Py + TRUST_CLASSES == TRUST_CLASS_ORDER + barrel/passive guards); `tests/unit/observation/{conftest,test_observation_envelope}.py` (construction/extra=forbid/vocab/mapping/trust-override/temporal/degrade/flag-attach) | ✅ implemented (this slice) |
| Gap matrix / ledger | Point 2 "Two-Envelope Architecture" MISSING → **PARTIAL** (evidence + owning phase WS-A5→WS-B); this ledger section | ✅ implemented (this slice) |

Build-time self-checks (serial, no full gate): parity file direct-run **10/10**; new pytest
suites **31 passed** (2.08s). `docs_drift.py --update` / `make ci-check` restamp deferred to
the full-program tip per the gate-policy directive (WS-A3/A4 precedent).

### Definition of done (WS-A5)

- Envelope-B field registry + runtime model + passive TS twin exist, held in lock-step by a
  parity test; the 10-class trust vocabulary equals `generated_registry.TRUST_CLASS_ORDER`.
- Adoption is flag-gated OFF with an additive, degrade-safe attach on the accepted path;
  `BaseEvent` (Envelope A) and the flat normalized consumption surface are unchanged.
- Ownership category, env-flag doc, unit + parity tests, and the gap-matrix/ledger updates
  move with the source; no validators weakened; no new ADR (ADR-012 still reserved).
- Canonical gate green at the full-program tip: `make ci-check` = 0, `git status --short`
  empty, `docs_drift.py --strict` clean.
- WS-B owns the enforcement half (source-trust/consent/idempotency/lineage + universal
  adapter convergence) — this slice deliberately leaves it to WS-B.

## WS-A6 — native event-type codegen (Swift/Kotlin regions generated from the event registry)

Stacked on `feat/sdk-universal-ingestion` — feat content at `4ffd69f5`,
tests/ownership at `623e94eb`, ledger close-out below (base = the WS-A5 tip
`e5a825af`), delivered in the consolidated program PR. Canonical gate deferred to the
full-program tip per the gate-policy directive; the build-time self-checks below are the
recorded evidence.

WS-A6 converts the hand-maintained iOS `AetherEventType` enum / `eventConsentPurpose`
dict and Android `EVENT_CONSENT_PURPOSE` map into **marker-delimited generated regions**
owned by `scripts/generate_contracts.py`, so a registry event-set or primary-purpose
change regenerates the native surfaces exactly as it already regenerates the TS/Python
twins and doc tables. The hand-authored Aether.swift/Aether.kt keep all non-region SDK
code — only the marker bodies are generated, and hand-editing them is not supported.

**The three generated regions (all spliced from `packages/shared/contracts/event-registry.json`):**

| Surface | Location | Content |
|---|---|---|
| iOS event enum | `packages/ios/Sources/AetherSDK/Aether.swift` — `@generated-start/end aether-event-types/ios-enum` | `AetherEventType` case list, grouped by registry family |
| iOS consent map | same file — `aether-consent-purposes/ios-map` | per-event `type → primary-purpose` dict |
| Android consent map | `packages/android/src/main/java/com/aether/sdk/Aether.kt` — `aether-consent-purposes/android-map` | per-event `"type" to "purpose"` mapOf |

Primary purpose = `requiredPurposes[0]`, defaulting to `analytics` when empty (same rule
the TS/Python twins use). Regions are byte-stable, so `python scripts/generate_contracts.py --check`
is idempotent.

**Drift fix delivered by regeneration.** The hand-maintained native maps had drifted on 5
agentic-trade/position events to purpose `agent` while the registry primary purpose is
`financial_activity` — a consent-gating bug the old key-set parity gate could not see.
Regeneration makes the registry authoritative: the five agent events whose registry
primary purpose is `financial_activity` — `agent_trade_order_observed`,
`agent_trade_fill_observed`, `agent_position_observed`,
`agent_portfolio_snapshot_observed`, `agent_performance_snapshot_observed` — now
carry `financial_activity`, and every other agent event carries `agent`. (Ledger
accuracy note, corrected in WS-A7: an earlier draft of this close-out cited
phantom names `agent_trade_executed` / `agent_position_opened` /
`agent_position_closed`, which are not registry event types.)

**Validator hardening (value-aware, never-weaken rule).** `make ci-check` (repo-doctor)
runs `validate_mobile_event_parity.py` but never the generator `--check`, so a
key-set-only parity gate would miss a single-event purpose re-gate inside a generated
region. The parity validator now also diffs each event's purpose **value** against the
registry on both native maps — the canonical gate catches value drift independently of
the generator path. Claim retirements landed in the same slice: four scripts'
"hand-maintained native maps / no generated native registry" language replaced with the
generator-owned reality (`validate_mobile_event_parity.py`, `validate_sdk_parity.py`,
`validate_sdk_release_alignment.py`, `repo_doctor.py`), plus this doc's sibling
`SDK_RUNTIME_PARITY.md` (native registries now generated; brittle "11-purpose" count
retired in favor of the generated per-event consent map).

| Workstream item | Deliverable | Status |
|---|---|---|
| Generator native emitters | `gen_ios_event_enum_section` / `gen_ios_consent_map_section` / `gen_android_consent_map_section` + shared `_splice_region` in `generate_contracts.py`; family-grouped, byte-stable, `--check` idempotent | ✅ implemented (this slice) |
| Regenerated native regions | Aether.swift enum + dict, Aether.kt map (403 events each) inside `@generated` markers; diffs confined to the three region bodies | ✅ implemented (this slice) |
| Value-aware parity backstop | `validate_mobile_event_parity.py` key-set diff unchanged + per-event primary-purpose value diff on both maps; regression-proven on the 5-event class | ✅ implemented (this slice) |
| Claim retirements | Hand-maintained-map claims retired in `validate_mobile_event_parity.py`, `validate_sdk_parity.py`, `validate_sdk_release_alignment.py`, `repo_doctor.py` (+ `SDK_RUNTIME_PARITY.md`) | ✅ implemented (this slice) |
| Codegen + parity unit coverage | `tests/unit/test_native_event_codegen.py` (14: emitters ↔ parity extractors, byte-stability, grouped order, analytics default, splice + apply writers); `tests/unit/test_mobile_event_parity.py` (15: hermetic main() seams, value-drift regression, value-map extractors) | ✅ implemented (this slice) |
| Ownership | New `mobile_native_regions` category in `repo_consistency_ownership.json` + `REPO_CONSISTENCY_OWNERSHIP.md` row (generator emitter + parity gate + region files → mirrors/tests) | ✅ implemented (this slice) |
| Gap matrix / ledger | This ledger section | ✅ implemented (this slice) |

Build-time self-checks (serial, no full gate): `generate_contracts.py --check` **exit 0**;
`validate_mobile_event_parity.py` **exit 0** (403×3 keys + per-event purpose); new pytest
suites **29 passed** (3.33s). `docs_drift.py --update` / `make ci-check` restamp deferred to
the full-program tip per the gate-policy directive (WS-A3/A4/A5 precedent).

### Definition of done (WS-A6)

- The iOS `AetherEventType` enum, iOS `eventConsentPurpose` dict, and Android
  `EVENT_CONSENT_PURPOSE` map are marker-delimited generated regions; generator `--check`
  is byte-stable and idempotent; the pre-existing 5-event purpose drift is corrected to
  the registry-authoritative values.
- `validate_mobile_event_parity.py` stays green and now enforces keys **and** per-event
  primary-purpose values, so value drift is caught under the canonical gate even though
  repo-doctor does not run the generator `--check`.
- Ownership category, codegen/parity tests, and claim retirements move with the source;
  no validators weakened; no new ADR (ADR-012 still reserved).
- Canonical gate green at the full-program tip: `make ci-check` = 0, `git status --short`
  empty, `docs_drift.py --strict` clean.
- WS-A7 next (re-point metric/privacy/retention truth into the Spine + un-stale the
  per-domain count prose recorded in WS-A4) — delivered in the WS-A7 section below.

## WS-A7 — re-point metric/privacy/retention truth to the spine + un-stale docs

Stacked on `feat/sdk-universal-ingestion` — generator/test at `8897cde4`, docs at
`e247883a`, ledger close-out below (base = the WS-A6 tip `6e9b1fe4`), delivered in
the consolidated program PR. Canonical gate deferred to the full-program tip per the
gate-policy directive; the build-time self-checks below are the recorded evidence.

WS-A7 closes the remaining WS-A contract-foundation debt recorded since WS-A4: the
generated event table carried only privacy class while authored SOT docs pointed at
it as the retention reference, and the authored `EVENT_REGISTRY.md` (plus six
dependent prose docs) had drifted far from the 403-type / 25-family spine.

**Retention Class made load-bearing (commit `8897cde4`).** `gen_event_table_md`
(scripts/generate_contracts.py) now emits a Retention Class column between Privacy
Class and Description, so `docs/_generated/event-registry-table.md` is the complete
per-event metadata surface — Event Type | Family | Required Purposes | Privacy Class
| Retention Class | Description (403 rows, deprecated marked). No other emitter
changed (native regions, TS/Python twins, and the consent/metric/integration tables
are byte-identical); the generator `--check` is idempotent. New pin suite
`tests/unit/test_event_registry_table_md.py` (6 tests) asserts the 6-column header,
one row per registry event in registry order, and — the backstop — that
`privacyClass` + `retentionClass` reproduce the spine for all 403 events.

**EVENT_REGISTRY.md rewritten (commit `e247883a`).** The doc claimed 248 types /
v8.10.0; its family table was missing five families (derivatives, interaction,
interop, privacy, stablecoin), carried a phantom `agentic` family, and the three
"agentic account / trading / AgentMail" + x402-observation sections used phantom
event-family labels `agentic_observability` / `x402_observability` (those events
live in families `agent` / `x402`; only the *service* directory is
`agentic_observability`). It falsely claimed the generated table shows Silver/Graph
projections, asserted core is analytics-only (`experiment` is marketing), and printed
an x402 "deprecated execution verbs" table the registry contradicts
(`x402_payment_submitted` / `_settled` are active SDK lifecycle verbs; only
`x402_payment` is deprecated). The rewrite now states the generated table is the authoritative per-event
reference, lists all 25 families with registry-exact counts / sdkEmitable counts /
consent purposes, catalogs the privacy and retention classes in use, and corrects the
journey (15), agent (64, backend/observation-plane), and x402 (26) narratives.
Prose counts were re-pointed to the current spine in six authored docs:
`FIRST_RELEASE_INTELLIGENCE_TELEMETRY_OPERATIONS` (267/21 → 403/25),
`COMMS_TRUTH_MATRIX` 1.1 (comms 15 → 23 events, now IMPL — closing the
WS-A4-recorded stale count),
`MEASUREMENT_INTEGRITY` (20 → 27 metrics, matching `registry.py` ↔ `metric-registry`
parity), `PRODUCT_INTELLIGENCE` (11 → 12 interaction events),
`UNIVERSAL_INTELLIGENCE_GRAPH_IMPLEMENTATION` validation log (248/8/20 → 403/12/25),
and `STABLECOIN_EVENT_REGISTRY` (financial/governance privacy split + per-class
retention made registry-exact). This ledger also absorbs two WS-A6-close-out accuracy
fixes (phantom agent drift-event names; deferred-table EVENT_REGISTRY row retired).

| Workstream item | Deliverable | Status |
|---|---|---|
| Retention Class column | `gen_event_table_md` emits Retention Class; `docs/_generated/event-registry-table.md` regenerated (403 rows, 6 columns); no other emitter changed; generator `--check` byte-stable | ✅ implemented (this slice) |
| Generated-table pin suite | `tests/unit/test_event_registry_table_md.py` (6 tests: header/separator, row-per-event registry order, spine-exact privacy + retention for all 403, purposes column, deprecation markers, title) | ✅ implemented (this slice) |
| EVENT_REGISTRY.md rewrite | 403 types / v8.12.0; 25-family table (counts + sdkEmitable + consent); phantom `agentic` / `agentic_observability` / `x402_observability` labels removed; Silver/Graph claim removed; core purpose corrected; x402 sole-deprecated truth; sdkEmitable taxonomy + privacy/retention class catalogs; generated-table pointer | ✅ implemented (this slice) |
| Prose-count re-point | FIRST_RELEASE (267/21→403/25), COMMS_TRUTH_MATRIX (15→23 IMPL), MEASUREMENT_INTEGRITY (20→27), PRODUCT_INTELLIGENCE (11→12), UNIVERSAL_INTELLIGENCE_GRAPH_IMPLEMENTATION (248/8/20→403/12/25), STABLECOIN_EVENT_REGISTRY (retention-exact) | ✅ implemented (this slice) |
| Ledger close-out | This section + WS-A row → complete; WS-A6 phantom-name + Deferred-row accuracy fixes | ✅ implemented (this slice) |

Build-time self-checks (serial, no full gate): `generate_contracts.py --check`
**exit 0**; pytest `test_event_registry_table_md.py` **6 passed**; EVENT_REGISTRY.md
family table / sdkEmitable counts / deprecation sets / class catalogs cross-checked
against `event-registry.json` (all match); 76 doc-named event types all resolve in
the registry; markdown table column-consistency scan over the 7 touched docs: 0 issues.
`docs_drift.py --update` / `make ci-check` restamp deferred to the full-program tip
per the gate-policy directive (WS-A3/A4/A5/A6 precedent).

### Definition of done (WS-A7)

- The generated event table carries Retention Class, so per-event privacy **and**
  retention are spine-derived and pinned by tests on a generated surface; the
  generator stays byte-stable and `--check` idempotent.
- `EVENT_REGISTRY.md` asserts only registry-true counts / families / purposes /
  classes and points readers at the generated table for the authoritative per-event
  enumeration; the six dependent prose docs carry current spine numbers.
- No validators weakened; no new ADR (ADR-012 still reserved); authored docs updated
  when the behavior (spine) changed; source-linked docs content-reviewed with
  `docs_drift.py --update` restamp deferred to the tip.
- Canonical gate green at the full-program tip: `make ci-check` = 0, `git status --short`
  empty, `docs_drift.py --strict` clean.
- WS-A (contract foundation) is complete — WS-B (adapter convergence) is next,
  reserved below.

## Later phases (reserved)

Workstreams A–E (the blueprint's own sequencing) begin after Phase 0 converges.
Phases are added to this ledger as they are scheduled; nothing below is claimed
built.

| Workstream | Scope (reserved) | Opens when |
|---|---|---|
| WS-A — Contract foundation | **WS-A1 + WS-A2 + WS-A3 + WS-A4 + WS-A5 + WS-A6 + WS-A7 done** (WS-A1 merged to main via #600; A2–A7 stacked on `feat/sdk-universal-ingestion` for the consolidated PR). WS-A complete: field-trust + semantic-level spine, privacy family, Envelope-B, native event-type codegen, and registry-re-pointed metric/privacy/retention docs | — (complete) |
| WS-B — Adapter convergence | SDK/webhook/connector/feed/import/harness/replay adapters that all produce Envelope B through one validated gateway; consent-on-every-path; idempotency-before-publish; ingestion-level replay with original-time preservation; kill deprecated `/v1/ingest` aliases (Invariants #1/#5/#8/#9/#15) | Phase 0 merged |
| WS-C — SDK hardening | Native identity → subject hints (delete client `/sdk/identity/resolve` re-stamping); native encrypted persistent queues; remove/relocate shared interpretation modules; regenerate `web/src/types.ts`; add native correlation fields (Invariants #4/#12/#16) | Phase 0 merged |
| WS-D — Backend interpretation | Typed `RelationshipFact` + `evidence_refs`; Episode engine; outcome truth store; Section-25 evidence dedupe; silver money → exact decimal/event-time valuation on by default (coordinate with `feat/financial-normalization` — do not build twice); mutation-gateway governance on by default (Invariants #7/#11/#13/#14) | Phase 0 merged |
| WS-E — Operations | Ingestion funnel telemetry; Kyber ingestion control plane + Observation Inspector; mount the already-built SDK-fleet view; golden cross-path fixture; SDK version-compatibility tiers; shadow/staged enforcement (Invariant #17, Gates G/H) | Phase 0 merged |

**ADR-012** is reserved for a future genuine decision (e.g. converge-on-one-
`observe` + the Envelope A→B contract) and is **not** created in Phase 0.

## Deferred (documented, not faked)

| Item | Why | Where tracked |
|---|---|---|
| Physical removal of the two legacy TS trees + orphaned backend modules | Kept alive by version-sync/fallback/test-suite/temporal coupling; removal is a clean dedicated later slice | `REPO_TRUTH_AND_GAP_MATRIX.md` — Deferred constraints |
| Envelope B + field-trust implementation | Deliberately out of Phase 0 | WS-A |
| Consent/privacy on every ingress path | Server-authoritative on `/v1/batch` only today | WS-B |
| Single observation model / normalization spine | ≥5 Bronze/Silver pipelines at baseline | WS-B |
| Kyber Observation Inspector + funnel metrics | No surface exists at baseline | WS-E |
| Stale source-linked docs (`INGESTION_CONTRACT.md`, `ENRICHMENT_LINEAGE.md`) | Contradict enforced code; corrected against sources in a later phase, not stamped (`EVENT_REGISTRY.md` corrected against the spine in WS-A7) | Deferred constraints |

## Definitions of done (all phases)

- Every phase ends with the canonical gate: `make ci-check` = 0, `git status --short`
  empty, `docs_drift.py --strict` clean, and no manual edits to generated docs.
- New work is *steered*, not reviewed-by-convention: each proposed feature is
  classified by (a) source-observable / transport / privacy / correlation → SDK or
  ingress; (b) resolve / derive / classify / decide → backend behind Envelope B +
  a trust class + a registry + evidence lineage; (c) which release-coverage row it
  rides; (d) which architecture invariant it touches. If it cannot be classified,
  it is not yet placed.
- PRs that touch a deprecated legacy tree must carry the acknowledgment
  (`docs/productization/sdk-universal-ingestion-alignment/**`) required by the
  `legacy_ingestion_tree_mutation` ownership category.
