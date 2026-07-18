---
title: "ADR-007: Domain Canonicalization — One Source of Truth per Domain"
slug: decisions/adr-007-domain-canonicalization
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
---

# ADR-007: Domain Canonicalization — One Source of Truth per Domain

**Status**: Accepted (8.12.0)

## Context

The staging-readiness audit found two domains carrying parallel, both-mounted
implementations, plus a resolved-but-worth-recording migration split:

- **Stablecoin** — two packages are mounted simultaneously:
  - `services/stablecoins/` (plural) — the observer/intelligence runtime stack
    (`ingestion`, `polling`, `providers`, `rpc_observer`, `solana_observer`,
    `aggregation`, `graph_projector`, `profile360`, `release_readiness`).
    Registered unconditionally in `main.py`; gated per-request by the
    `stablecoin_intelligence` settings namespace; serves `/v1/stablecoin`.
  - `services/stablecoin/` (singular) — the economic-intelligence surface
    (`valuation`, `flows`, `support`, `finality`, `registry`, `reconciliation`,
    `service`, `foundation`). Mounted behind `settings.stablecoin.api_enabled`;
    serves `/v1/stablecoins`.
  - The two overlap on `finality`, `models`, `registry`, `reconciliation`,
    `support`, use **two settings namespaces** (`stablecoin_intelligence` vs
    `stablecoin`) and **two contracts** (`packages/shared/stablecoin.ts` vs
    `stablecoin-intelligence.ts`), and the package↔route naming is **inverted**
    (singular package → plural route and vice-versa).
- **Derivatives** — one package (`services/derivatives/`) exposes **two route
  surfaces** (`routes.py` → `/v1/derivatives` product; `runtime_routes.py` →
  `/v1/derivatives/runtime`) with parallel `models.py`/`runtime_models.py` and
  `reconciliation.py`/`runtime_reconciliation.py`.
- **Migrations** — the raw-SQL foundation files under
  `Backend Architecture/migrations/*.sql` were already adopted into the Alembic
  chain idempotently (see ADR-006). Alembic is the single source of truth; the
  raw files are SUPERSEDED-in-place. A single Alembic head is confirmed
  (`20260730_consent_control_plane_seed`).

## Decision

Declare one canonical source of truth per domain and enforce it with tests,
without a high-risk physical merge that cannot be runtime-validated in the same
change:

1. **Stablecoin canonical package**: `services/stablecoins/` (plural, observer/
   intelligence runtime) is canonical for observation, ingestion, finality,
   reconciliation, graph projection, and Profile360. `services/stablecoin/`
   (singular, economic-intelligence) is retained as the complementary
   economic-value surface and is **deprecated for the overlapping concerns**
   (`finality`, `registry`, `reconciliation`, `support`): those must converge on
   the plural package. New behavior for those concerns lands only in the plural
   package.
2. **Derivatives canonical surface**: the runtime surface
   (`runtime_routes.py` + `runtime_models.py` + `runtime_reconciliation.py`,
   `/v1/derivatives/runtime`, gated by `settings.derivatives.api_enabled`) is
   canonical for the ingestion/observation runtime; the product surface
   (`routes.py`, `/v1/derivatives`) is retained as the tenant product read
   surface. New adapter/ingestion behavior lands only on the runtime side.
3. **Migrations**: Alembic is canonical (ADR-006). Raw-SQL files stay
   SUPERSEDED-in-place. Exactly one Alembic head is required and tested.

## Enforcement (this change)

- Route-presence tests assert the canonical tenant + Kyber routers mount.
- A route-conflict test asserts no two mounted operations share the same
  `(method, path)` — the real correctness risk from parallel surfaces.
- A single-Alembic-head test asserts exactly one head.
- Deprecated overlapping modules carry an explicit deprecation note pointing to
  the canonical package.

## Removal conditions (tracked debt — not done here)

Physical unification of the two stablecoin packages (and collapsing the
derivatives `*_models`/`*_reconciliation` pairs) is deferred because it requires
merging two settings namespaces, two contract files, and their tests, and must
be validated against a live surface. It is safe to remove the deprecated
stablecoin overlap modules once: (a) the plural package exposes every economic
concern the singular package does, (b) the `stablecoin` and
`stablecoin_intelligence` settings namespaces are merged behind one flag family,
(c) the two contract files are consolidated with a versioned compatibility
export, and (d) route-parity tests pass against the unified surface.

## Consequences

- One declared canonical owner per domain; regressions caught by route/head
  tests.
- No behavior change and no gate risk in this change; the parallel surfaces keep
  working (both default OFF) while convergence proceeds.
- The deferred physical merge is explicit debt with concrete removal conditions,
  not a hidden fork.
