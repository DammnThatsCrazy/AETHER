# Social360 + Relationship Fidelity — DEPENDENCY MAP

Milestone M0 deliverable. Substrate dependencies and milestone ordering, grounded in today's repo.

## Substrate dependency view

```
Social provider sources
        │  (requires UPR present: provider_runtime/ ✅; social plugins NEW → M2)
        ▼
Bronze evidence          (present: provider_runtime/raw_store.py ✅)
        │
        ▼
Social Silver facts      (NEW service + contracts → M1 contracts, M3 facts; tables per §104)
        │
        ├──▶ Identity Resolution binding   (present: services/identity/ ✅ CONSUME)
        ├──▶ Semantic/campaign/comms/economic context  (present ✅ CONSUME)
        └──▶ Data rights / consent gates   (present authorities ✅ CONSUME)
        │
        ▼
RELATIONAL SPINE (NEW — M1 contracts/registries ⇒ M6 promotion/motifs ⇒ M5 incentive ⇒ M7 fidelity)
        │            all computation via shared/computation/ ✅ (definitions M7)
        ▼
Graph Mutation Gateway   (present: shared/graph/mutation_gateway.py ✅ — SOLE write path, §52)
        │
        ▼
Relationship360 / Gold   (registry entry exists (in_flight); provider NEW)
        │
        ▼
Path Intelligence        (present: path_scoring/traversal ✅ EXTEND in M8; fidelity-aware)
        │
        ▼
Exploration Fabric       (services/exploration + shared/exploration ✅ present;
        │                  projection_engine ⚠️ branch-only — GATES M9)
        ▼
Lenses SocialFi / EngagementFi / Narrative (NEW → M9)  →  Aether / Kyber / Noesis surfaces (M10)
```

Legend: ✅ present on base · NEW created by this program · ⚠️ branch-only / partial · M# milestone.

## Key cross-dependencies and risk edges

1. **M1 (contracts) is the hard prerequisite** for M3 (silver facts), M5 (incentive), M6
   (promotion/motifs), M7 (fidelity), M9 (filters), M10 (surfaces). Nothing else starts code
   before M1 lands.
2. **M2 (UPR social)** depends on M1 capability vocabulary + existing UPR seams. It can run
   partly parallel to M3. Expected outcome is largely `code_complete`/`externally_blocked`
   (no live social credentials) — honest status, not a defect (§19, §158).
3. **M4 (legacy honesty migration)** is independent of UPR provider richness; it only needs
   Social360 canonical output to delegate to. Order M4 as soon as M3 has a minimal canonical
   Social360 read path.
4. **M5 (IncentiveContext)** consumes Campaign360 (`services/campaign/`) + Economic360
   (`services/economic/`) references and `shared/temporal/` windows. No new campaign engine.
5. **M6 (promotion/motifs)** → **M7 (fidelity)** ordering: fidelity consumes evidence groups
   and asserted candidates produced by promotion; fidelity recompute triggers (§47) drive
   restatement (M11).
6. **M8 (paths)** extends present `shared/graph/path_scoring.py` + `traversal.py` and the
   `operational_intelligence/models.py` path models. Must respect predicate transitivity
   classes (§23) and epistemic ceiling (§66). Do NOT replace Dijkstra/Yen (§68).
7. **M9 (lenses) ⚠️ GATED**: `shared/projection_engine/` is NOT on origin/main. Options to
   resolve before M9: (a) the owning lane merges to main, or (b) this program re-bases onto a
   main that carries it. M9 is thereby sequenced last among backend milestones but its
   registry entries (lens-registry.json, filter fields §84) can be authored earlier with M1.
8. **Olympus corpus → tenant overlay (§14)**: unresolved. Any corpus-derived relationship
   graph write is blocked until the projection rule is resolved + documented (or recorded
   `externally_blocked`). Does NOT block tenant-scoped social facts.
9. **graph_motifs authority**: motif outputs must be emitted as indicators under the existing
   `graph_motifs` canonical authority (relationship360/fraud360 scope), not as a new claim
   engine (§42, §101).

## Milestone ordering (per blueprint §139–153, adjusted for reality)

```
M0 (recon/ledger)                    ← in progress; gate: authority map complete
  └─▶ M1 contracts/registries        ← prerequisite for all code
        ├─▶ M2 UPR social            (provider plugins; honest status)
        ├─▶ M3 Social Silver plane
        ├─▶ M4 Legacy honesty migration   (after minimal M3 read path)
        ├─▶ M5 IncentiveContext
        └─▶ M6 Promotion + motifs
              └─▶ M7 Fidelity          (consumes M5/M6)
                    └─▶ M8 Fidelity-aware paths
                          └─▶ M9 Lenses  ⚠️ waits on projection_engine on base
                                └─▶ M10 Product surfaces (Aether/Kyber/Noesis)
                                      └─▶ M11 Migration/backfill/decommission
                                            └─▶ M12 Hardening + release evidence
```

Parallelizable (disjoint file ownership, per §152): M2‖M3 after M1; M5‖M6 after M1;
frontend-surface contracts can be authored with M1 but not shipped (flags OFF §122).
