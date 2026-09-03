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

## Phase 0 (current) — convergence bedrock

Branch `feat/sdk-universal-ingestion` (base `6a11394f`, tracking `origin/main`).
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

## Later phases (reserved)

Workstreams A–E (the blueprint's own sequencing) begin after Phase 0 converges.
Phases are added to this ledger as they are scheduled; nothing below is claimed
built.

| Workstream | Scope (reserved) | Opens when |
|---|---|---|
| WS-A — Contract foundation | Field-trust/authority taxonomy + per-field minimum trust + Level A/B/C + missing vocabularies in the Contract Spine; Envelope B server-side; per-event metadata load-bearing and generated; Swift/Kotlin generation; re-point metric/privacy/retention truth into the Spine (Blueprint Points 2/3/10/13, Invariants #2/#16) | Phase 0 merged |
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
| Stale source-linked docs (`EVENT_REGISTRY.md`, `INGESTION_CONTRACT.md`, `ENRICHMENT_LINEAGE.md`) | Contradict enforced code; corrected against sources in a later phase, not stamped | Deferred constraints |

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
