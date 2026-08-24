---
title: Intelligence Projection Vertical Slice Checklist
slug: source-of-truth/intelligence-projection-vertical-slice-checklist
section: source-of-truth
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - docs/decisions/ADR-010-intelligence-projection-plane.md
  - docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md
  - packages/shared/contracts/intelligence-projection-registry.json
last_synced_commit: f3568cec
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
---

# Intelligence Projection Vertical Slice Checklist

Every follow-up 360 PR must satisfy this Definition-of-Done **before** its
registry row is flipped to `implemented`. A projection becomes `implemented`
only when the full vertical slice lands — registry row, shared contract
conformance, runtime provider, API + route, surface, UI, evidence, tenant
isolation, graph mutation policy, tests, readiness, and docs — and `make
ci-check` is green. Anything less keeps the row at `in_flight` (or
`registered`). See `docs/decisions/ADR-010-intelligence-projection-plane.md`
and `docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md`.

## Gate

- [ ] This PR is a **vertical slice** for one projection (the slice that
      moves it from `in_flight` → `implemented`), and it touches nothing the
      registry's `pendingAuthority` / DAG validation would forbid.
- [ ] `make ci-check` exits 0 on this branch (canonical completion gate) —
      run after every commit, not just at the end.

## 1. Registry row

- [ ] `implementationState` is `implemented` in
      `packages/shared/contracts/intelligence-projection-registry.json`.
- [ ] **Zero pending** — `pendingAuthority` and `pendingReference` are empty.
- [ ] **Zero unresolved refs** — every `surfaceIds`, `metricRefs`,
      `canonicalAuthorities`, `hardDependencies`, `projectionDependencies`,
      `subjectKinds`, and capability/spine ref resolves against its real
      registry (or backend enum); the validator reports no violations.
- [ ] **Converged bindings** — `legacyBindings.migrationMode == "converged"`
      and every `legacyBindings.routes` / `surfaceIds` / `services` binding
      resolves against `config/route_registry.yaml`, the surface registry, and
      real paths on disk.
- [ ] `implementationBlueprint` is a non-empty `.md` path under `docs/`
      (existence checked at `implemented`).
- [ ] `ownsCanonicalTruth` is `false` (structurally enforced — do not flip it).

## 2. Shared contract conformance

- [ ] The provider consumes the shared contracts
      (`ProjectionRequest`, `ProjectionContext`, `ProjectionResult`,
      `ProjectionSection`, `ClaimEnvelope`) from
      `Backend Architecture/aether-backend/shared/intelligence_projections/contracts.py`
      / `packages/shared/intelligence-projection.ts`.
- [ ] **No redefinitions** — the slice reuses canonical `EntityRef`,
      `EvidenceRef`, `PageRequest`, and the time-range primitive; it does not
      declare a second of any of them (imports/parity test passes).
- [ ] `SectionState` values are exactly the generated union
      (`available|empty|missing|degraded|not_applicable|unknown`).

## 3. Runtime provider

- [ ] A provider module implements `IntelligenceProjectionProvider`
      (`typing.Protocol` — `projection_id`, `contract_version`, `async
      project(...)`) — there is no `Base360` superclass to inherit from.
- [ ] The provider is registered in `ProviderRegistry`
      (`.../intelligence_projections/registry.py`) with `source=` and a
      compatible `contract_version`.
- [ ] The provider raises only `ProjectionError` subclasses and never mutates
      canonical state outside the gateway.

## 4. API + route classification

- [ ] The projection's public endpoint(s) are registered/classified in
      `config/route_registry.yaml` (no unregistered route prefix).
- [ ] No *new* generic public 360 route prefix is introduced; existing
      `legacyBindings` reference already-registered prefixes. A projection MAY
      add one classified read-only prefix as part of its own vertical slice
      (the `infrastructure360` `/v1/infrastructure` precedent — every route a
      GET, no catch-all), never a generic projection route.

## 5. Surface join

- [ ] The projection's `surfaceIds` are all present in
      `packages/shared/contracts/surface-capability-registry.json` (joined via
      the Exploration Fabric; the projection registry never defines surfaces).
- [ ] New surfaces (if any) are appended to the surface registry — UI-less is
      legal (the `temporal_observatory` precedent) — and their generated
      surface artifacts are regenerated.

## 6. UI surface

- [ ] A tenant UI surface exists for the projection (page/adapter), or the
      surface is explicitly UI-less and that is declared, matching the
      `temporal_observatory` / `product_intelligence` precedent.
- [ ] The UI renders typed section states and formats values — it never
      recomputes or reinterprets them.

## 7. Evidence requirements

- [ ] `requiresEvidence` is honored: every claim in the result carries a
      reused `EvidenceRef`; an ungrounded claim is a typed
      `missing`/`degraded` state, never a silent assertion.
- [ ] Evidence is tenant-scoped; cross-tenant evidence leakage is tested and
      absent.

## 8. Tenant isolation

- [ ] The projection request and result are tenant-scoped end to end; no
      shared mutable state across tenants.
- [ ] A tenant-isolation test proves tenant A cannot see tenant B's sections
      or evidence.

## 9. Graph mutation policy via gateway

- [ ] `graphMutationPolicy` is `read_only` (no write path) or
      `canonical_gateway_only`.
- [ ] If `canonical_gateway_only`: all writes go through
      `GraphMutationGateway.apply(MutationIntent)`; there is no other write
      path, and the graph-policy test passes.
- [ ] `read_only` projections have no write path at all.

## 10. Tests

- [ ] Tests cover: registry schema, dependency DAG (acyclic), inventory
      honesty (bindings resolve), runtime registration (duplicate/version),
      tenant safety, typed degradation (missing/incompatible/raise →
      `missing`/`degraded`/`not_applicable`), evidence, graph policy, and
      order-resilience (the slice's row change is order-stable and leaves
      other rows byte-identical).
- [ ] The full targeted pytest set passes:
      `python -m pytest tests/unit/test_intelligence_projection_*.py -q --tb=short`
      and
      `python -m pytest "Backend Architecture/aether-backend/tests/unit/" -k intelligence_projection -q --tb=short`.

## 11. Readiness — no `production_ready` claim

- [ ] Flipping to `implemented` makes **no** readiness claim: no
      `production_ready`, no certification token, no readiness-ladder entry is
      derived from `implementationState`. `readiness.py` output is
      presentation-only and asserted to never emit such a token.

## 12. Source-linked doc review + stamp

- [ ] This slice's behavior changes are reflected in
      `docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md` (and the
      generated registry table / dependency graph), reviewed — not blindly
      stamped.
- [ ] `last_synced_commit` is updated **after** review via
      `python scripts/docs_drift.py --update`, and
      `python scripts/docs_drift.py --strict` exits 0.

## 13. Final gate

- [ ] `make repo-doctor-fix` regenerates generated artifacts, then
      `make ci-check` exits 0 with a clean `git status --short`.
- [ ] The PR body carries full context (what / why / value / how it works /
      what it means for the graph), including this checklist's completed
      state and a pointer to the registry row it converges.
