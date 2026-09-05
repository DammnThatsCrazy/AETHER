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

Branch `feat/sdk-universal-ingestion` (rebased onto `bfea2e93` = `origin/main` head at landing, which carried Communication360 #596 on top of the 360 program #593).
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

## WS-A1 (current) — blueprint canonicalization + spec recovery

Branch `feat/sdk-univ-ws-a1` off `d379a9d2` (= `origin/main` head after the
Phase 0 squash-merge, PR #599).
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

## WS-A2 (current) — field-trust taxonomy in the Contract Spine

Branch `feat/sdk-univ-ws-a2` off `b4fc4d18` (= `origin/main` head after the
WS-A1 squash-merge, PR #600).
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
| Integration + final gate | `make repo-doctor-fix` **70/0** (wrote the synced-doc reindex — `REPO-INDEX.md` `scripts` 184→185 / `tests` 541→542 once the two new files were tracked); 11 source-linked docs genuinely reviewed against the additive change and restamped (also healing the pre-existing `AWS-DEPLOYMENT.md` staleness from #598 in-band); **`make ci-check` 73/0** at HEAD `424a761a`, `git status --short` empty, `docs_drift.py --strict` exit 0 | ✅ implemented (this slice) |

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

## Later phases (reserved)

Workstreams A–E (the blueprint's own sequencing) begin after Phase 0 converges.
Phases are added to this ledger as they are scheduled; nothing below is claimed
built.

| Workstream | Scope (reserved) | Opens when |
|---|---|---|
| WS-A — Contract foundation | **WS-A1 + WS-A2 done —** WS-A3–A7: per-field minimum trust + Level A/B/C; missing vocabularies; Envelope B server-side; Swift/Kotlin generation; re-point metric/privacy/retention truth into the Spine (Blueprint Points 2/3/10/13, Invariants #2/#16) | WS-A1 merged |
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
