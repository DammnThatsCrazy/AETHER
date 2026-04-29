# v-Next ADRs

One ADR per capability in [`../BUILD_SPEC.md`](../BUILD_SPEC.md). Each pins the
interface, the build sequence, the failure modes, and the rollback path.

| # | Capability | ADR |
|---|---|---|
| 1 | Bitemporal + Witness Signatures | [001-bitemporal-witness.md](./001-bitemporal-witness.md) |
| 2 | Conformal Abstention + Explainability | [002-conformal-abstention.md](./002-conformal-abstention.md) |
| 3 | Mission Graph (stream-materialized) | [003-mission-graph.md](./003-mission-graph.md) |
| 4 | Agent Balance Sheet + EIP-712 Attestations | [004-balance-sheet-attestations.md](./004-balance-sheet-attestations.md) |
| 5 | Coverage Autopilot (AL router) | [005-coverage-autopilot.md](./005-coverage-autopilot.md) |
| 6 | Collusion Motif Detection | [006-collusion-motifs.md](./006-collusion-motifs.md) |

## ADR template

```
# ADR-NNN: <Capability>

Status: Proposed | Accepted | Superseded
Owner: <subsystem owner>
Flag: AETHER_FEATURE_<NAME>  (default: off)

## Context
<2-4 sentences: what exists today, what is missing, why now.>

## Decision
<File path(s), public interface, schema additions. Concrete signatures.>

## Consequences
<What this touches. What it does NOT touch. SDK/API impact.>

## Build sequence
1. ...
2. ...

## Failure modes & rollback
<Single failure surface. What goes wrong. How to disable in <5 min.>

## Acceptance
<Measurable bar for "done".>
```

## Conventions

- Every capability is gated by a single `AETHER_FEATURE_<NAME>` env flag, default off.
- New schema fields are additive and nullable. No drops, no renames.
- New endpoints land under `/v2/` or as new paths under existing `/v1/` namespaces. Existing `/v1/` contracts are not modified.
- New SDK types are additive and exported behind a `experimental:` prefix in `packages/shared/events.ts` until the corresponding ADR moves to Accepted.
- Each ADR has exactly one "single failure surface" file. Logic outside that file consumes a stable interface, so disabling the surface (or returning a no-op) reverts the capability cleanly.
