# Agent Team Charter — Mobile/Continuity/Notification Completion Program

Single authority for **who works where** in the C5-C9 completion program
(M1-M8 per the approved finish plan). Orchestrator = the main agent.
Everything here is read by every specialist before starting; it prevents
duplicate work and conflicts on shared paths.

## Roles

| Role | Does | Does NOT |
|---|---|---|
| **Orchestrator** | Sequence milestones; write shared paths; construct commits; run gates; own the merge/release decision | Delegate shared-path writes; certify its own work at M8 |
| **Discoverer** (Explore agent, per milestone) | Regenerate the bounded work packet from `context-index.json` + symbol search | Rescan whole repo; implement |
| **Specialist** (implementation agent, per milestone fan-out) | Implement on its **disjoint** allowed paths; return schema-validated structured output | Touch shared paths; touch another specialist's paths |
| **Verifier** (M8 lens agent) | Review a single lens; produce schema-validated findings + verdicts | Implement; certify its own implementation |
| **Completeness critic** (per milestone) | Ask "what's missing" (unwired producer, unregistered route, missing storage-policy/feature-surface entry) | Implement fixes |

## Work packet contract

Each specialist reads:
1. Its packet in `reports/mobile-productization/work-packet-ledger.json` (objective, reuse
   targets, allowed paths, contracts, invariants, acceptance, required tests).
2. The topic entries in `reports/mobile-productization/context-index.json` (authoritative
   files to read before trees).
3. This charter.
4. `reports/mobile-productization/decision-log.md` — and **appends a reuse statement** for
   every new module (existing system considered → why it cannot satisfy → new boundary →
   validator preventing duplication).

Do NOT rescan the repo for what the packet already names.

## Shared conflict surfaces — orchestrator-owned, serialized writes

Specialists must never write these; they propose, the orchestrator integrates:

- `Backend Architecture/aether-backend/main.py` (route mounts, router unmounts)
- `Backend Architecture/aether-backend/config/settings.py` (feature flags default OFF)
- `Backend Architecture/aether-backend/services/runtime/specs.py` (worker registration)
- `packages/shared/index.ts` (TS twin registry)
- `package.json` (npm workspaces)
- `Makefile` (gates)
- `config/storage_policies.yaml` (storage-policy coverage)
- `alembic/versions/` (single-head invariant)
- `docs/_generated/**` (never hand-edited; regenerate via `make repo-doctor-fix`)

## Implementation fan-out (per milestone, disjoint paths)

| Milestone | Disjoint specialist paths | Orchestrator integrates |
|---|---|---|
| M1 (C2-remainder) | projection-agent ‖ validator-agent | inbox model, shared index, Makefile, tests |
| M2 (mobile platform) | mobile-config-agent ‖ mobile-ui/offline-agent ‖ compliance-agent | alembic, workspaces, Makefile, storage policies, shared index |
| M3 (C5 projections + Aether) | projections-agent ‖ mobile-screens-agent ‖ desktop-NC-agent | main.py, settings, shared index |
| M4 (Kyber screens) | kyber-mobile-screens-agent | main.py (kyber gateway mounts) |
| M5 (C6 sync) | producers-agent ‖ continuation-router-agent ‖ frontend-surfaces-agent ‖ mobile-surfaces-agent | main.py, shared index, emitter wiring |
| M6 (C7 actions) | action-adapter-agent ‖ kyber-tier-ui-agent | main.py, settings, shared index |
| M7 (demo + docs) | demo-seed-agent ‖ distribution-docs-agent | demo targets, Makefile |
| M8 (C9 review) | 6 lens verifiers in parallel ‖ adversarial refute pass | remediation commits |

## Verification model

- **Deterministic gates** between milestones: `make ci-check` (canonical), contract parity
  tests, route-conflict ratchet, single-alembic-head, storage-policy coverage, clean
  generated docs. Human-language review never substitutes for these.
- **M8 lenses** (six, parallel, verifying — never self-certifying): architecture/duplication;
  tenant-operator security; data truth/evidence; concurrency/delivery/reliability; mobile
  privacy/store compliance; operational/release honesty. Then an adversarial refute pass
  (independent agents default to refuting; only survivors are confirmed findings).

## Reuse-before-build (prohibited duplicates)

Second inbox, second command plane, second policy engine, second graph truth, second
Profile360/Campaign360 calculation, second saved-view/Noesis store, second credential
system — all prohibited. A specialist that believes it needs a duplicate must record the
reuse statement and stop, not build.

## Honest boundaries (unchanged)

Native iOS-sim/Android-emulator compile, store submission, provider live sends, and the
physical-device matrix remain `externally_blocked` (see
`reports/mobile-productization/external-blockers.json`). No claim of production readiness
without `scripts/production_status.py` scorecard evidence. No fabricated evidence at M8.
