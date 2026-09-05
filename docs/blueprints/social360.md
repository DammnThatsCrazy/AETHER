---
title: "Social360 Blueprint — Relationship-Fidelity Extension to the Relational Intelligence Spine"
slug: blueprints/social360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 15
toc_depth: 3
---

# Social360 — Extension of the Relational Intelligence Spine

**Projection id**: `social360` · **Kind**: `relationship_360` ·
**Graph mutation policy**: `read_only` · **`ownsCanonicalTruth`**: `false`

This page is the repo home of the *Social360 + Relationship Fidelity Extension to
the Relational Intelligence Spine* program. It describes what the program builds,
the architectural invariants that bind it, and its honest current state. It is
**not** a vertical-slice convergence claim: the `social360` row of
`packages/shared/contracts/intelligence-projection-registry.json` remains
`in_flight`, and this page records the milestone state as it is, milestone by
milestone.

**Authoritative program specification** (implementation authority, dated
2026-08-21, 163 numbered sections):
`~/Desktop/Aether Social360 + Relationship Fidelity Extension to the Relational
Intelligence Spine — Full Development & Implementation Blueprint.md`
(md5 `29210bc8fb2ee5d766d697e01a8fd424`). Machine-readable program state,
gap ledger, dependency map, ownership map, legacy-social truth matrix and
open-PR collision log live in [`reports/social360/`](../../reports/social360/).

## What this is

Social360 is a **bounded social-evidence and state domain** — it answers *"what is
socially observable about this entity?"* and feeds canonical facts into the
Relational Intelligence Spine. The spine extension adds six governed concerns that
turn graph connectivity into **relationship intelligence**:

1. relationship-predicate semantics (a governed registry, not hard-coded logic);
2. relationship promotion (a state machine from raw observation to persistent
   relationship state);
3. relationship motifs (registry-driven higher-order structure detection);
4. `IncentiveContext` (a first-class, temporal, provenance-bearing context);
5. `RelationshipFidelity` (a multidimensional vector — never one universal scalar);
6. fidelity-aware, relationship-intelligent path composition over the existing
   `#357` traversal engine.

Relationship360 remains the canonical owner of cross-domain relationships;
Social360 never becomes a second relationship graph.

## What it deliberately is NOT

No second graph, identity resolver, provider framework, traversal engine,
semantic engine, computation system, findings system, "SocialFi backend", or
universal social score. No `organic = true` derived from `none_observed`
incentive. No behavioral similarity as identity evidence. No unavailable →
`0` conversion. No path that outranks the epistemic authority of its weakest
material hop.

## Why

Aether already has entities, graph edges, social/communication/economic/campaign/
agent/temporal/semantic observations, relationship Gold state and 1–N-hop path
traversal. What is missing is the **semantic and epistemic layer that converts
evidence about relationships into relationship intelligence**: the difference
between *"Aether knows A mentioned B"* and *"Aether can explain the
evidence-backed relationship between A and B — how durable, reciprocal,
contextual, independent and incentive-exposed it is, how it changed over time,
and what propagated through it."* Legacy social work also carries assumptions the
modern doctrine rejects (fixed cross-platform audience-overlap percentages,
missing-data-as-zero metrics, underspecified "influence", pre-UPR provider
behavior, social facts not integrated into relationship promotion).

## How it fits the existing architecture

```text
Provider sources → UPR → Bronze → Social Silver facts
   (identities · connections · interactions · content · communities · metrics)
        │  identity resolution · semantic/campaign/economic/comms context · data rights
        ▼
   RELATIONAL INTELLIGENCE SPINE      (predicates · evidence grouping · promotion ·
        │                               motifs · IncentiveContext · fidelity ·
        ▼                               contradiction · temporal restatement)
   Graph Mutation Gateway (sole write path)
        ▼
   Relationship360 / relationship assertions
        ▼
   1–N hop path intelligence (extended, fidelity-aware) → Exploration Fabric lenses
        ▼
   SocialFi / EngagementFi / Narrative  →  Aether · Kyber · Noesis
```

Every new canonical relationship write passes through the existing Graph Mutation
Gateway; all fidelity computations run on the Canonical Computation Substrate;
social provider ingestion converges onto UPR; the contract spine generates the
Python/TypeScript twins; the existing semantic/narrative reducers and path engine
are extended, never duplicated.

## Governing invariants (release-blocking)

- **The graph remains authoritative** — Social360 contributes evidence and domain
  state; Relationship360 owns cross-domain relationships.
- **Unknown is never zero** — a social or relationship surface may not turn
  unavailable data into `followers = 0`, `engagement_rate = 0`,
  `relationship_strength = 0` or `influence = low` unless zero/low is actually
  evidence-backed. `0` is a measurement; `unknown` is a state.
- **Incentive exposure is context, not disqualification** — and absence of a
  detected incentive is never automatically `organic`.
- **Existence confidence ≠ relationship strength** — they are separate
  dimensions.
- **One interaction does not become a durable relationship by default.**
- **Correlated evidence is not independent evidence** (duplication/correlation
  damping; evidence independence grouping).
- **Multi-hop paths do not manufacture truth** — a path cannot exceed the
  epistemic ceiling of its weakest material hop.
- **No universal person score**; contextual indices exist only as governed
  Computation Definitions.
- **Identity resolution and relationship resolution remain separate** — the
  listed similarity signals never merge identities.
- **Relationship evidence is explainable** — every non-primitive assertion
  resolves to evidence, promotion policy, model/rule, contradictions, and
  temporal state.

## Milestones

Full program ledger and dependency map: [`reports/social360/PROGRAM_STATE.yaml`](../../reports/social360/PROGRAM_STATE.yaml)
and [`reports/social360/DEPENDENCY_MAP.md`](../../reports/social360/DEPENDENCY_MAP.md).

| # | Milestone | Status |
|---|---|---|
| M0 | Reconnaissance and truth ledger (`reports/social360/`) | complete |
| M1 | Canonical contracts and registries (Social360 facts, IncentiveContext, predicate + motif registries, fidelity schema; py/ts parity; ownership/tests) | complete — ci-check 63/0 (76e1ab56) |
| M2 | UPR social provider convergence | implemented — 63/0 gate (b89edb3f) |
| M3 | Social Silver plane (deterministic normalization, identity + data-rights integration) | implemented — 63/0 gate (b89edb3f) |
| M4 | Legacy social honesty migration (fabricated zeros, fixed overlap, influence defaults) | implemented — 63/0 gate (b89edb3f) |
| M5 | IncentiveContext resolution (temporal segmentation, lineage, campaign/economic integration) | implemented — 63/0 gate (b89edb3f) |
| M6 | Relationship promotion and motifs (evidence grouping, contradiction, gateway projection) | implemented — 63/0 gate (b89edb3f) |
| M7 | Relationship fidelity (canonical Computation Definitions, independence, damping) | implemented — 63/0 gate (b89edb3f) |
| M8 | Fidelity-aware path intelligence (hop contract, epistemic ceiling, snapshot staleness) | implemented — 63/0 gate (b89edb3f) |
| M9 | Exploration Fabric lenses — SocialFi / EngagementFi / Narrative | implemented — 63/0 gate (b89edb3f) |
| M10 | Product surfaces — Aether / Kyber / Noesis | implemented — 63/0 gate (b89edb3f) |
| M11 | Migration, replay, backfill, decommission | implemented — 2026-09-04 close-out (64/0 gate); residuals D-04/D-05/D-OPEN recorded |
| M12 | Hardening and release evidence | implemented — 2026-09-04 close-out (64/0 gate, guardrail #64); no release-readiness claim |
| M13 | A&B relationship read surface + spine activation seams (read APIs, Noesis spine intents, influence decomposition, D-04 seam, silver write path, full-plane replay harness) | implemented — 2026-09-04 A&B slice (targeted 159/0 + full-plane 4/0); flag-gated OFF; no release-readiness claim |

M2–M10 landed 2026-09-04 as the parallel waves-1–4 build (agents/sub-agents),
integrated and validated by the canonical gate `make ci-check` (env-stripped)
**63 passed / 0 failed** at `b89edb3f`. Per-milestone targeted-test counts and the
recorded residual seams (M6↔M7 independence resolver; historical-consent evaluation
on the legacy social aggregator) live in
[`reports/social360/PROGRAM_STATE.yaml`](../../reports/social360/PROGRAM_STATE.yaml)
(key decisions D-04/D-05). M11 (migration/decommission) and M12 (hardening/release
evidence) were closed out 2026-09-04 with a static guardrail validator (gate #64) and
close-out reports under `reports/social360/` (`M11_MIGRATION_DECOMMISSION.md`,
`M12_HARDENING_EVIDENCE.md`); the §154 source-of-truth doc decision is recorded D-06. "Implemented" here means code + honesty tests landed flag-gated OFF —
it is **not** a vertical-slice convergence claim; the `social360` projection row
remains `in_flight`.

**M13 (A&B, 2026-09-04) — relationship read surface + spine activation seams.** Built
under *Address A & B*: the D-04 M6↔M7 independence seam is now **filled**
(`services/relationship_promotion/evidence_independence.py` provides the M6 module M7
names, and `services/relationship_intelligence/coordinator.py` is its first runtime
caller — proven end to end by the hermetic full-plane replay test
`tests/relationship_intelligence/test_full_plane.py`, 4/0). The relationship read APIs,
consent enforcement surface and spine-run meters land in
`services/relationship_intelligence/{reads,routes,consent,coordinator}.py`
(`GET /v1/relationships/{source}/{target}/fidelity|explain|influence`); the Noesis
relationship-spine read intents (G048) and influence-as-propagation decomposition
(G043) are implemented; the six `silver_social_*_facts` tables gained DDL +
repositories + writer routing. All of this stays flag-gated OFF — the live provider
pull, the enforce-flag flip and real SLO baselines remain release-gated residuals
(ledger D-07). **No release-readiness claim.**

Rollout is flag-gated (`AETHER_SOCIAL360_ENABLED=false`,
`AETHER_SOCIAL_UPR_ENABLED=false`, `AETHER_RELATIONSHIP_MOTIFS_ENABLED=false`,
`AETHER_RELATIONSHIP_FIDELITY_MODE=off`, `AETHER_PATH_FIDELITY_ENABLED=false`,
`AETHER_SOCIAL_LENSES_ENABLED=false`, `AETHER_RELATIONSHIP_SPINE_NOESIS_ENABLED=false`);
new product behavior defaults OFF until
explicit activation. Provider readiness remains honest
(`code_complete` is never promoted to `provider_live` without external evidence).
The Olympus-corpus → tenant-overlay projection rule (§14 P0 prerequisite) is
recorded `D-OPEN` in the program ledger and must be resolved and documented
before corpus-derived relationships are written to the tenant-scoped graph.

## Status of this page

`status: experimental` — the projection row is `in_flight`, not product-ready.
Completion is judged only by the canonical repo gates (`make ci-check`) per
milestone, never by this page. Standalone §154 source-of-truth docs (SOCIAL360 / spine / fidelity / …) are recorded
as a release-gated residual (D-06) rather than authored now: their linked sources live
on the flag-gated `in_flight` plane, so this home doc + the program ledger + the
M11/M12 reports carry the authority until the surface leaves `in_flight` at productization.
