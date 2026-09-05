---
title: "Aether Spine P0 — Spine Conformance Checklist (Phase 6)"
slug: architecture/spine-p0-conformance-checklist
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
source_files:
  - packages/shared/contracts/spine-registry.json
  - packages/shared/contracts/graph-mutation-registry.json
  - packages/shared/contracts/consent-registry.json
  - packages/shared/contracts/temporal-policy-registry.json
  - packages/shared/contracts/readiness-vocabulary.json
  - packages/shared/contracts/evidence-manifest.schema.json
  - packages/shared/graph-contract.ts
  - scripts/validate_contracts.py
  - docs/source-of-truth/DATA_RIGHTS_LEDGER.md
last_synced_commit: "pending"
estimated_read_minutes: 7
toc_depth: 3
---

# Aether Spine P0 — Spine Conformance Checklist

**Status:** Phase 6 evidence map (ADR-011 D6). The 14 ids/titles are authoritative
verbatim from `packages/shared/contracts/spine-registry.json`.

## Enforcement note

The validator **refuses a spine-row state flip while a conformance gap is open**
(ADR-011 D6). That refusal lands with the conformance gate (Phase 6); until then
this checklist is the map the gate reads. Every item must resolve to a **real**
file, validator, registry, or test — never prose. An item with no evidence yet is
a **true gap**, named `open` with the phase that closes it; a row must not flip
state with an open gap.

## How to read a spine row's conformance state

Each registry row carries the 14 checks as `id → "open" | "verified"`. `verified`
means the row satisfies the item end to end — the evidence anchor exists and the
row resolves against it. `open` blocks any state flip toward `CANONICAL`. The
`spines` array is empty and the Phase 2 validator has not shipped, so every item
is `open` for every row until rows and the gate land; the anchors below are what a
`verified` claim must point at.

## The 14 items

### 1. `authority_non_ownership_statement` — Authority and non-ownership statement
**Demands:** the spine states what it owns and explicitly what it does **not** own
or re-answer. **Evidence:** registry row schema (ownership + non-ownership);
`scripts/lib/intelligence_projection_validation.py` (`SPINE_INDEX` /
`pendingAuthority`); `docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md`.
**Demonstrate:** every claimed id resolves to its owning registry; the
non-ownership list names who does own each excluded id. **Done:** nothing is
re-defined; Phase 2 validator accepts the statement.
**Gap (true today):** no rows and no ownership validator yet — closes Phase 2.

### 2. `canonical_contract_registration` — Canonical contract registration
**Demands:** the spine's contract refs resolve against the registry that owns each
id. **Evidence:** owning registries under `packages/shared/contracts/`
(`consent-registry.json`, `graph-mutation-registry.json`,
`temporal-policy-registry.json`, `readiness-vocabulary.json`,
`surface-capability-registry.json`, …) cross-checked by `scripts/validate_contracts.py`.
**Demonstrate:** row refs the registry id for each contract; an unresolved ref is
declared `pending` with reason + milestone. **Done:** cross-registry validation
green; no id re-defined; no parallel registry.
**Gap:** spine cross-registry validator ships Phase 2; anchors are real.

### 3. `port_adapter_declaration` — Port and adapter declaration
**Demands:** the spine declares consumed and published ports and the adapter
boundary each maps to. **Evidence:** registry row schema (consumed / published
ports); surface/adapter vocabulary in `surface-capability-registry.json`.
**Demonstrate:** row names each port, its adapter/code path, and what it
publishes. **Done:** every port resolves to an adapter or declared `pending`.
**Gap (true today):** no spine port vocabulary or validator yet — Phase 2 schema,
Phase 4 joins.

### 4. `dependency_dag_validation` — Dependency DAG validation
**Demands:** hard/soft/runtime/policy dependencies form an order-independent DAG
with no silent or cyclic references. **Evidence:** registry row schema (dependency
kinds); validator precedent in `scripts/lib/intelligence_projection_validation.py`.
**Demonstrate:** row declares dependency kinds; every ref resolves or is `pending`;
the DAG is acyclic. **Done:** DAG validation green — order-independent composition.
**Gap (true today):** no spine DAG validator or rows yet — closes Phase 2.

### 5. `typed_degradation_behavior` — Typed degradation behavior
**Demands:** a not-yet-complete spine publishes typed states through the envelope
(`unavailable` / `degraded` / `unknown` / `not_applicable`) rather than forcing
callers to invent behavior. **Evidence:** projection precedent (ADR-010 D5) —
typed `missing` / `degraded` / `not_applicable` section states; the degradation
mapping (`unavailable` ≈ `missing`, …) in SPINE_P0_ARCHITECTURE.md.
**Demonstrate:** row's envelope declares its typed state for each missing
capability/data/policy. **Done:** envelope vocabulary is the spine-plane
generalization of the projection states — no parallel state machine.
**Gap (true today):** spine envelope + degradation states ship Phase 3; the projection states are the real precedent.

### 6. `temporal_watermark_behavior` — Temporal and watermark behavior
**Demands:** the spine preserves event/ingestion/valid/system time, watermark
position, and `as_of` replay — never silently substituting a guessed time.
**Evidence:** `temporal-policy-registry.json` (dispositions, enforcement modes,
per-family skew/lateness bounds); `as_of` point-in-time **replay** in
`packages/shared/graph-contract.ts`. **Demonstrate:** row reads/writes honor `as_of`
replay + watermark; temporal reason codes govern ingestion. **Done:** `as_of`
replay + watermark demonstrable end to end on the row.
**Gap:** spine temporal/watermark envelope fields ship Phase 3 (no producer claimed
until one ships).

### 7. `evidence_restatement_behavior` — Evidence and restatement behavior
**Demands:** canonical state is evidence-backed; corrections restate with an
attributable record rather than silently overwriting. **Evidence:**
`evidence-manifest.schema.json`; `tests/graph/test_evidence_backed_mutations.py`;
provenance / restatement machinery. **Demonstrate:** row's mutations carry
`evidence_refs`; a restatement path is declared and attributable. **Done:** no
evidence-less write; restatement leaves an attributable record.
**Gap:** none material — machinery real; per-row demonstration awaits rows.

### 8. `tenant_consent_rights_retention_residency_export` — Tenant, consent, rights, retention, residency, and export behavior
**Demands:** the spine honors tenant isolation, consent, rights, retention/delete/
export, and residency before any data movement. **Evidence:** `consent-registry.json`
+ `ConsentPolicyDecision` (`services/policy`); `DataRightsGrant` +
`DATA_RIGHTS_LEDGER.md` (`services/integrations/data_rights`); `DataRetentionPolicy`
(`services/security`); DSR fan-out (`services/dsr_propagation`, `DSR_COMPONENTS`).
**Demonstrate:** row's rights boundary references the consent/rights/retention ids
it honors; DSR/export fan-out declared per component. **Done:** fail-closed
tenant/consent/rights/retention/residency/export behavior is traceable to a real
grant + decision on the row.
**Gap:** none material — anchors real; row-level wiring awaits rows.

### 9. `graph_mutation_policy` — Graph mutation policy
**Demands:** every graph write follows a declared policy (`read_only` or
`canonical_gateway_only`) through the Graph Mutation Gateway. **Evidence:**
`graph-mutation-registry.json` (`graphMutationPolicies`, mutation types, actor
kinds); Graph Mutation Gateway (`MutationIntent` → `apply`) + ledger.
**Demonstrate:** row declares its policy in the registry enum; gateway path named.
**Done:** a write on the row is impossible outside its declared policy + gateway.
**Gap:** none material — registry + gateway real.

### 10. `api_event_ui_kyber_integration` — API / event / UI / Kyber integration
**Demands:** the spine is exposed through existing surfaces — APIs, events, UI,
Kyber — never a bespoke parallel surface. **Evidence:**
`surface-capability-registry.json`, `kyber-feature-surface-manifest.json`,
`event-registry.json`; Kyber control surface. **Demonstrate:** row's
surfaces/adapters resolve to registered surface + Kyber features. **Done:** Phase 4
join validator resolves every surface/adapter ref; no parallel surface registry.
**Gap:** surface/readiness/Kyber join validator ships Phase 4; registries are real.

### 11. `readiness_entitlement_integration` — Readiness and entitlement integration
**Demands:** the spine's readiness key joins `readiness-vocabulary.json`
**presentation-only**, never emitting a certification token or `production_ready`.
**Evidence:** `readiness-vocabulary.json` + `scripts/validate_readiness_vocabulary.py`;
`evidence-manifest.schema.json`; `CAPABILITY_MANIFEST.md`; ADR-010 D3 / ADR-011 D5.
**Demonstrate:** row's `readinessKey` is a registered token; certification state
held separately and honestly. **Done:** the row carries no certification claim
beyond what evidence supports; `production_ready` is never inferred.
**Gap:** none material — vocabulary + validator real; per-row join is Phase 4.

### 12. `security_compliance_observability_evidence` — Security / compliance / observability evidence
**Demands:** the spine names its security/compliance controls and observability /
recovery path with evidence, not assertion. **Evidence:** `services/security`
(access/egress policy, `audit_ledger`, evidence packs); observability/metrics
conventions; registry row schema (controls, observability/recovery).
**Demonstrate:** row names each control and the evidence pack that backs it.
**Done:** every named control points at a real evidence pack or declared gap.
**Gap (true today):** no spine compliance/observability evidence packs exist and no row declares controls — authoring lands as rows register (Phase 7).

### 13. `migration_recompute_rollback_compatibility` — Migration, recomputation, rollback, and compatibility plan
**Demands:** the spine declares how it migrates, recomputes, rolls back, and stays
compatible across versions. **Evidence:** replay/recompute/restatement machinery
(temporal replay, graph history, restatement jobs); registry row schema.
**Demonstrate:** row authors its plan referencing concrete replay/recompute/rollback
entry points. **Done:** the plan preserves historical results on upgrade/downgrade
and names a rollback path.
**Gap (true today):** the per-row plan is authored with the row — no row or gate yet (Phase 7); underlying machinery is real.

### 14. `positive_negative_replay_isolation_golden_tests` — Positive, negative, replay, isolation, and golden-scenario tests
**Demands:** the spine ships positive, negative, replay, isolation, and golden
tests in the shared conformance suite. **Evidence:** conventions —
`tests/integration/test_comms_golden_scenario.py`,
`tests/unit/exploration/test_exploration_planner_golden.py`,
`tests/graph/test_graph_replay_workloads.py`, tenant-isolation battery
(`tests/security/test_graph_tenant_isolation.py`, `test_journey_tenant_isolation.py`, …).
**Demonstrate:** row's PR runs the four quadrants against its envelope, mutation,
temporal, and rights behavior. **Done:** quadrants demonstrated in the shared
conformance suite for the row.
**Gap:** conventions real; the spine-shared conformance test suite is net-new (Phase 6).

Related: [SPINE_P0_ARCHITECTURE.md](./SPINE_P0_ARCHITECTURE.md) (§7); 13-item projection
vertical-slice precedent (`INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`);
[ADR-011](../decisions/ADR-011-spine-composition-kernel.md) (D6);
[SPINE_P0_PHASES.md](../plans/SPINE_P0_PHASES.md) (Phase 6);
[IRRL_NAMING_OVERLAY.md](./IRRL_NAMING_OVERLAY.md) (Phase 5 label map).
