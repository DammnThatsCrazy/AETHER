---
title: Repo Truth and Gap Matrix — SDK + Universal Ingestion Alignment
slug: productization/sdk-universal-ingestion-alignment/repo-truth-and-gap-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
---

# Repo Truth and Gap Matrix

## Method

Read-only gap assessment against the live tree on **2026-09-03** at branch
`feat/sdk-universal-ingestion` (base `71c37d0d`, now on `origin/main` head).
The assessment classified every section of the 34-section **SDK + Universal
Ingestion Alignment Blueprint** (blueprint sections 1–34; section 0 is the
executive-directive preamble, not a requirement row) against the repository.

**Authority rules** (how "repo truth" is established when trees conflict):

1. **Deployed beats un-deployed.** Only the Python monolith is built/referenced
   by deployment authority: root `docker-compose.yml`, `.github/workflows/deploy.yml`
   (ECR), `AWS Deployment/main.tf` (+ `AWS Deployment/aether-aws/terraform/…`),
   `config/runtime_deployment.yaml`. Neither TypeScript duplicate tree appears in
   any of them.
2. **Live ingress beats README claims.** Canonical SDK ingress is `POST /v1/batch`
   in `Backend Architecture/aether-backend/services/ingestion/batch.py`; SDKs
   target `api.aether.io` / `ingest.aether.so`, never port `3001`.
3. **Generated/registry artifacts beat hand-maintained mirrors.** The Contract
   Spine source is `packages/shared/contracts/event-registry.json`; generated TS/
   Python twins and gated docs that declare it as source are preferred over
   hand-maintained lists.
4. **Where a README contradicts enforced code, the code wins** (and the doc is
   flagged for correction, not trusted).

**Classification semantics.** `EXISTS` = present and conforms; `PARTIAL` =
present with real gaps; `MISSING` = net-new absent; `MISALIGNED` = present but
contradicts the blueprint.

**Owned by:** `platform@aether`. Authored document (no `source_files`) — the
matrix is the curated rendering of the delivered read-only assessment, kept
drift-exempt on purpose.

## Ledger

One row per blueprint section (1–34). Classification reflects the repository at
the Phase-0 baseline, before this slice's deprecations/gates. Evidence paths are
repo-relative.

| Blueprint § | Classification | File evidence | Owning phase |
|---|---|---|---|
| 1 — Target end-to-end architecture | **MISALIGNED** | Two `/v1/batch` acceptors + two lake stacks; canonical path exists only in Python: `Backend Architecture/aether-backend/services/ingestion/batch.py`, root `docker-compose.yml`; duplicate claims in `Data Ingestion Layer/README.md` (:3001) and `Data Lake Architecture/README.md` | Phase 0 (deprecate duplicates) → WS-B |
| 2 — Point 1: Observation Boundary | **MISALIGNED** | No single observation model after adapters; heterogeneous envelopes on one validated topic; five+ Bronze/Silver pipelines — `…/services/ingestion/workers.py`, `…/bronze_bulk.py`, `Backend Architecture/migrations/…/20260720_silver_import_facts.py` (synthesized `TEXT source_event_id`) | WS-B |
| 3 — Point 2: Two-Envelope Architecture | **MISSING** | Envelope B = zero implementation; `BaseEvent` is the one flat envelope — `packages/shared/events.ts` | WS-A |
| 4 — Point 3: Contract Spine as Generator | **MISALIGNED** | Spine real + drift-gated, but native iOS/Android registries are hand-maintained and documented never-generated; `packages/web/src/types.ts` is a drifted hand-mirror; only consent is generated — `packages/shared/contracts/event-registry.json`, `scripts/generate_contracts.py`, `packages/ios/Sources/AetherSDK/Aether.swift`, `scripts/validate_mobile_event_parity.py` | WS-A (+ Phase 0 drift gates) |
| 5 — Point 4: Universalize Ingress Adapters | **MISALIGNED** | Deprecated `POST /v1/ingest/events[/batch]` still mounted and publishes un-validated events into the "validated" topic; webhook/feed/import paths distinct — `Backend Architecture/aether-backend/main.py`, `…/services/ingestion/routes.py` | Phase 0 (kill aliases) → WS-B |
| 6 — Point 5: Identity via Subject Hints | **MISALIGNED** | Web is hints-only/aligned; native SDKs stamp canonical top-level ids and re-stamp client-side after `/sdk/identity/resolve`; client `identityConfidence` persisted verbatim to Silver — `packages/ios/Sources/AetherSDK/Aether.swift`, `packages/android/src/…/Aether.kt`, `…/services/ingestion/validation.py` (`strip_canonical_entity_id`), `…/services/silver/projectors/touchpoint_projector.py` | WS-C |
| 7 — Point 6: Temporal Observation Contract | **PARTIAL** | `EventTemporalEnvelope` server-built but flag-gated default OFF and dropped at the Silver boundary (projectors re-read the raw timestamp string) | WS-D |
| 8 — Point 7: Correlation First-Class | **MISALIGNED** | Correlation stored as opaque JSONB only; no columns/registry; dropped at promotion; native SDKs carry none | WS-D (+ WS-C native correlation) |
| 9 — Point 8: Provenance & Evidence Native | **PARTIAL** | Raw store + `source_record_id` back-links real; evidence chain not typed; Section-25 evidence dedupe unimplemented | WS-D |
| 10 — Point 9: Consent/Privacy/Minimization/Retention | **MISALIGNED** | Server-authoritative **only on `/v1/batch`**; live feed persists raw payloads with no scrub; webhook/connector governance gate default-OFF; import rows persist raw PII with `privacy_class` hardcoded `'behavioral'` — `…/services/integrations/webhook_policy.py`, `…/services/ingestion/acquisition_privacy.py` | WS-B |
| 11 — Point 10: Ingress Trust & Credential Classes | **MISSING** | `PUBLIC_CLIENT`…`OPERATOR_REPLAY` and `trust_class` return zero repo hits; `auth.py` `credential_class` defaults to `'legacy'` with no enforcement semantics | WS-A (taxonomy) → WS-B (enforcement) |
| 12 — Point 11: Durability/Ordering/Idempotency/Replay Universal | **MISALIGNED** | Batch strong (Bronze-before-ACK); webhook/connector dedupe the bronze row but **re-publish unconditionally**; import ack = job receipt; native queue delete-before-ack; no ingestion-level replay | WS-B (+ WS-C native persistent queue) |
| 13 — Point 12: Typed Validation & Degradation | **PARTIAL** | `status ∈ {accepted,duplicate,rejected}`; degraded = `accepted` + reason string; quarantine collapses to `rejected`; Silver money still `missing→0.0`, currency → `'USD'` | WS-B |
| 14 — Point 13: Event Semantics vs Derived Intelligence | **MISSING** | No Level A/B/C semantics, no `aether_internal` origin, no `claim_type`/`model-version`/`evidence` on events; a public SDK key can emit any registered type (validation checks membership only) | WS-A |
| 15 — Point 14: SDK Core + Adapter + Facades | **MISSING** | No CI gate enforces SDK thinness; `packages/mobile-core` is an unrelated API client; interpretation modules ride inside the SDK graph | Phase 0 (import-boundary gate) → WS-C |
| 16 — Point 15: Universal Backend Projection Pipeline | **MISALIGNED** | Five+ Bronze/Silver pipelines (SDK dispatcher · imports inline to `silver_import_facts` · DUNE lake promotion · connectors Bronze-only · semantic bypassing to `silver_semantic_observations`) instead of one normalization spine | WS-B |
| 17 — Point 16: Ingestion Observable in Kyber | **MISSING** | No Observation Inspector (RAW→…→METRICS); no ingestion funnel metrics; SDK-fleet stack built but unmounted; the one pipeline hook calls a phantom `GET /v1/health/pipeline` | WS-E |
| 18 — Point 17: Conformance/Compatibility/Migration Testing | **PARTIAL** | Drift/parity gates strong; no golden cross-path fixture; exhaustive native parity forces iOS/Android to mirror all 398 event types incl. server-only/derived; shadow/staged enforcement absent | Phase 0 (first gates) → WS-E |
| 19 — Point 18: Controlled Release Program | **MISSING** | Governance encodes no ingestion-architecture invariants; physical-dir realignment and duplicate-tree deprecation pending; ADR numbering collision present at baseline | Phase 0 |
| 20 — Web SDK runtime example | **EXISTS** | Web is the aligned reference surface — thin/observe-only, registry-driven consent, endpoint `https://api.aether.io` (`packages/web/src/index.ts`); nuances: DNT advisory-only, consent defaults all-false | Phase 0 (preserve as bedrock) |
| 21 — Ingestion runtime | **MISALIGNED** | Three heterogeneous envelopes share `SDK_EVENTS_VALIDATED`; Silver workers branch on `source_service`/payload keys — `…/services/ingestion/workers.py`; deprecated alias publishes un-validated into the same topic | WS-B |
| 22 — Backend processing example | **PARTIAL** | Silver normalizers/projectors real on the canonical path; branching on source required; projectors re-read the raw client timestamp (temporal envelope dropped) | WS-D |
| 23 — Webhook runtime example | **MISALIGNED** | Public provider-webhook + API-feed bypass the canonical gateway; consent/scrub/minimization default-OFF; signature verification is strong but the governance gate is not | WS-B |
| 24 — Agent/Execution runtime example | **MISSING** | Aether-internal execution capture absent/bypassing the gateway (backend Noesis recorder writes `ai_execution_facts` directly); Agent Layer emits no telemetry; Execution360 has no implementation | WS-D |
| 25 — Connector runtime example | **PARTIAL** | Connector signature verification + Bronze-only raw store real; consent never applied on connector pulls; `commerce.order.*` events dead-end at Bronze (no commerce Silver projector); idempotency re-publish gap | WS-B |
| 26 — Canonical graph primitives | **PARTIAL** | Entities/relationships/journeys real; episodes/outcomes absent; Section-25 evidence dedupe unimplemented; no typed `RelationshipFact`/resolution-method/validity | WS-D |
| 27 — Interaction with other blueprints | **MISALIGNED** | `docs/source-of-truth/repo_consistency_ownership.json` still lists the TS trees as authorities SDK behavior derives from; `EVENT_REGISTRY.md`/`INGESTION_CONTRACT.md` contradict enforced code. (This slice adds the deprecation ownership rows to `docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md`.) | Phase 0 (deprecation + governance correction) |
| 28 — Thinness invariant | **MISSING** | No CI gate enforces SDK thinness; `packages/shared/commerce-bridge.ts` + `packages/shared/economic-metrics.ts` ship interpretation into the SDK graph; native vocab never generated | Phase 0 (SDK import-boundary gate) → WS-C |
| 29 — Mandatory architecture invariants | **MISALIGNED** (aggregate: 1 EXISTS · 9 PARTIAL · 6 MISALIGNED · 2 MISSING) | See the 18-gate invariant matrix below | Phase 0 (governance) + all WS |
| 30 — Release coverage matrix | **MISSING** | No per-surface capture/privacy/idempotency/temporal/correlation/provenance/replay coverage is enforced; several matrix rows (feed, import, connector, webhook) are unserved today | WS-B |
| 31 — Downstream coverage matrix | **PARTIAL** | SDKs thin (read/no-write) ✓; Bronze raw ✓; normalizers/identity partial; episodes/outcome engines absent | WS-D |
| 32 — Release gates (A–G) | **MISSING** | None of Gates A–G is encoded in CI; Phase 0 adds the first two (canonical-tree ownership, SDK import boundary); Gate G (Kyber ops) awaits WS-E | Phase 0 → WS-E |
| 33 — What success looks like | **PARTIAL** | Success conditions partly met (SDK thinness largely holds); single-observation-model + Envelope B remain the blockers | Phase 0 (bedrock) + WS-B |
| 34 — Final target architecture | **MISSING** | Repository does not yet match the target tree; physical realignment deferred; Phase 0 begins convergence (deprecate duplicates, resolve ADR collision, add gates) | Phase 0 |

### Invariant matrix (§29 — the 18 hard gates)

Per-invariant classification at the Phase-0 baseline (Blueprint §29, verbatim
invariants; see `TARGET_ARCHITECTURE.md` for the verbatim checklist).

| # | Invariant | Status | One-line reality |
|---|---|---|---|
| 1 | One observation model after adapters | MISALIGNED | 3 heterogeneous envelopes share the "validated" topic; ≥5 Bronze/Silver pipelines; imports bypass the gateway; dual `/v1/batch` acceptors |
| 2 | One Contract Spine governs ingestion vocabulary | PARTIAL | Spine real + drift-gated, but event-level metadata only (no fields/trust), metric truth inverted, stale `EVENT_REGISTRY.md` |
| 3 | No SDK owns backend intelligence | PARTIAL | Import graph clean, but `shared/commerce-bridge.ts` + `economic-metrics.ts` ship interpretation into the SDK graph; no CI thinness gate |
| 4 | No public source may assert canonical identity truth | PARTIAL | Strip real on batch + web aligned, but native SDKs stamp canonical top-level ids and re-stamp via client `/sdk/identity/resolve`; `identityConfidence` persisted verbatim to Silver |
| 5 | Every accepted observation is durable before acknowledgment | PARTIAL | Exact on `/v1/batch`; webhook/connector re-publish on duplicate; import ack = job receipt; native queue delete-before-ack |
| 6 | Every observation has tenant provenance | PARTIAL | Canonical path gold-standard; legacy `/v1/ingest` alias + feed uneven |
| 7 | Every provider record preserves source provenance | PARTIAL | Raw store + `source_record_id` real; evidence chain not typed; connector commerce dead-ends at Bronze |
| 8 | Every ingestion path implements idempotency | PARTIAL | Batch strong; webhook/connector dedupe the bronze row but re-publish unconditionally; connector key from a random `uuid4`, not the provider id |
| 9 | Consent and privacy policy apply to every path | MISALIGNED | Enforced only on `/v1/batch`; feed writes raw with no scrub; webhook/connector gate default-OFF; import rows persist raw PII |
| 10 | Raw/source data and normalized graph truth remain distinguishable | EXISTS | object-backed/hash-chained Bronze vs Silver, `source_record_id` back-links |
| 11 | Temporal source information is never discarded | PARTIAL | Server `EventTemporalEnvelope` exists but flag-gated default OFF and dropped at the Silver boundary |
| 12 | Correlation IDs survive normalization | MISALIGNED | Stored only as opaque JSONB; no columns, no registry, dropped at promotion; native SDKs have no correlation field at all |
| 13 | Missing/empty/zero/degraded states remain distinct | MISALIGNED | `status ∈ {accepted,duplicate,rejected}`; degraded = `accepted`+reason; quarantine collapses to `rejected`; Silver money still `missing→0.0`, currency→`'USD'` |
| 14 | Derived claims retain evidence and model/policy lineage | MISSING | Edges/relationships carry no `evidence_refs`; outcome store returns `None`; identity audit drops per-signal evidence; `claim_type` exists only in Noesis |
| 15 | Replays never masquerade as new occurrence time | MISALIGNED | No ingestion-level replay; bus `Event.timestamp = now` at construction re-stamps replay time; no `replayed_at`/run-id |
| 16 | SDK schemas are generated rather than manually drifting | MISALIGNED | TS events generated, but `web/src/types.ts` is a drifted hand-mirror; native iOS/Android registries are hand-maintained and code-generation is a documented non-goal |
| 17 | Kyber can trace observations end-to-end | MISSING | No Observation Inspector; no ingestion funnel metrics; fleet stack built but unmounted; the one pipeline hook hits a phantom endpoint |
| 18 | Backend intelligence changes do not require SDK releases | PARTIAL | No version-compatibility tiers; backend strips `library.version` and treats all clients identically; capability manifest is thin |

Tally at baseline: **1 EXISTS · 9 PARTIAL · 6 MISALIGNED · 2 MISSING** (the two
deepest MISSING: #14 derived-claim lineage and #17 end-to-end observability; the
six MISALIGNED are the present-but-contradictory set that Phase 0's gates must
steer future work away from).

## Deprecated legacy inventory

Phase 0 deprecates without deleting (see [Deferred constraints](#deferred-constraints)).
The ownership-map category introduced by this slice (`legacy_ingestion_tree_mutation`
in `docs/source-of-truth/repo_consistency_ownership.json` /
`docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md`) requires this
`docs/productization/sdk-universal-ingestion-alignment/**` directory as the
acknowledgment surface when any of these trees is touched.

| Legacy artifact | Why deprecated | Evidence | Disposition |
|---|---|---|---|
| `Data Ingestion Layer/` | Un-deployed TypeScript duplicate of the backend; `package.json` `name` is literally `"aether-backend"`; port `:3001`; own `/v1/batch` | `Data Ingestion Layer/package.json`, `Data Ingestion Layer/README.md` | DEPRECATED — do-not-extend banner (Phase-0 commit 3); no code may be added |
| `Data Lake Architecture/` | Un-deployed TypeScript duplicate lake (own Bronze/Silver/Gold, 90/365/730d retention, own `/v1/batch`) parallel to the Python lake/silver with financial-7y retention | `Data Lake Architecture/README.md` | DEPRECATED — do-not-extend banner (Phase-0 commit 3); no code may be added |
| Orphaned `Backend Architecture/` root modules | Dead legacy outside `aether-backend/` — `auth.py cache.py common.py events.py graph.py limiter.py logger.py repos.py routes.py settings.py migrations/ mnt/ services/{delegation,journey-service,web3}` | `Backend Architecture/README.md` | DEPRECATED — do-not-extend; enumerated in `Backend Architecture/README.md` (Phase-0 commit 3) |

Kept alive (as of baseline) only by `scripts/bump_version.py` version-sync,
`config/runtime_fallbacks.yaml`, `config/test_suites.yaml`, and
`validate_temporal_integrity` coupling — the coupling that must be cut before any
later removal slice.

## ADR collision record

At baseline `docs/decisions/` held a number collision: **two files claimed ADR-007** —
`ADR-007-domain-canonicalization.md` (Aug 6) and
`ADR-007-observation-only-execution-invariant.md` (Sep 3, the newer file).
Phase 0 resolves it by **renumbering the observation-only ADR to ADR-011**
(`docs/decisions/ADR-011-observation-only-execution-invariant.md`) — the smaller
blast radius (links in `ADR-008` and `docs/audits/DOCS_REVIEW_BACKLOG.md`).
After the rename `docs/decisions/` holds ADR-001…ADR-011 with no gap. Merging the
two ADR-007 files would be wrong — they decide unrelated topics.

## Phase gates added

Phase 0 adds the first two CI gates that encode the invariants as governance
(`repo_doctor.py` wiring is the integrator's responsibility; this page records
the intent):

| Gate | Validator | Semantics |
|---|---|---|
| Canonical-tree ownership (no-new-duplicate) | `scripts/validate_canonical_ingestion_trees.py` | Registered-missing → FAIL (shrink-only registry `scripts/allowlists/repo_tree_ownership.json`); tracked-unregistered new top-level dir or new backend child → FAIL (route to canonical or register + architect review). Roles: `canonical`, `deprecated` (with `deprecated_at`+`disposition`), `house`, `registered-not-deployable` (Agent Layer). |
| SDK import boundary (thinness) | `scripts/validate_sdk_import_boundary.py` | Scan SDK surfaces only; forbidden internals derived from backend package names; `actual−allowlist` and `allowlist−actual` both FAIL. Allowlist `scripts/allowlists/sdk_internal_import_allowlist.json`. |

See `EXECUTION_STATE.md` for the phase that lands them.

## Deferred constraints

- **No physical deletion in Phase 0.** The legacy trees are kept alive by
  version-sync / runtime-fallback / test-suite / temporal-integrity coupling;
  removal is a clean, dedicated later slice once that coupling is cut. Banners +
  single-owner registration stop new code entering the dead trees at near-zero risk.
- **No Envelope B / field-trust build in Phase 0** — that is Workstream A
  (contract foundation). This slice fixes the governance that lets new work steer
  toward the invariants; it does not implement them.
- **No new ADR in Phase 0.** ADR-012 is reserved for a future genuine decision
  (e.g. converge-on-one-`observe` + the Envelope A→B contract).
- **No hand-editing of generated docs.** `docs/_generated/**` is regenerated via
  `make repo-doctor-fix` (integrator-owned), never hand-edited.
- **Stale source-linked docs flagged, not stamped.** `EVENT_REGISTRY.md` (calls
  consent a hand-mirrored `CONSENT_MAP`), `INGESTION_CONTRACT.md` (says native
  SDKs are in-memory-only), and `ENRICHMENT_LINEAGE.md` contradict enforced code;
  they are corrected against their sources in a later phase, not blind-stamped.
