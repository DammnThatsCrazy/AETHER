---
title: 360 Surfaces
slug: 360-surfaces
section: concepts
visibility: P
audience: [buyer, dev-senior]
status: experimental
since_version: "0.1.0"
---

# 360 Surfaces

## Overview

360 surfaces are productized, governed read/query views over canonical Aether
authorities, including graph, identity, evidence, temporal, execution, and
economic sources. Each 360 composes a contextual view of a specific entity
type or concept while preserving provider provenance and policy state.

## Product catalog

The complete catalog contains 18 product surfaces. Its machine-readable
contracts and slot-to-provider section mappings are maintained in
`packages/shared/contracts/intelligence-projection-registry.json` and
rendered in the generated [Product 360 Surface Catalog](../_generated/360-surface-catalog.md).
The 18 product surfaces are a separate catalog from the technical projection
providers that supply their reads.

## Architecture

360 surfaces are governed projections over canonical authority data. They do
not own a competing system of record; each domain's canonical authority
remains responsible for its own truth.

## Backend contract status

The shared backend contract now defines a typed frame request/response,
catalog-bound slots, projection lineage, evidence refs, freshness, quality,
policy disposition, actor attribution, delegation, and frame degradation. The
frame builder evaluates a tenant- and surface-bound policy result before it
reads projections, requests only sections needed by permitted slots, and
composes through the existing intelligence projection runtime. Missing policy
is a closed gate.
Until a provider can constrain its reads to approved fields and preserve
field-to-claim dependencies, a slot marked redacted is suppressed before its
projection providers are queried.

The common frame path is mounted at `POST /v1/experience360/frames`; the
tenant-scoped catalog and live technical-provider availability are exposed at
`GET /v1/experience360/catalog`. Tenant scope comes from authenticated request
state. Frame and slot reads use the central `AccessControlService` by default;
slot authority domains are checked before projection reads. An unclassified
catalog authority, unavailable/malformed evaluator, or mismatched policy scope
fails closed and suppresses reads. This access layer complements canonical
source-level consent, purpose, and field-redaction decisions; it does not
replace them.

This is an implementation foundation, not a claim that all surfaces are live.
The 18 product surfaces are source-aligned to the checked-in backend SSOT and
remain distinct from the technical projection providers that serve them.
Provider availability still varies.
Agent and Execution 360 require explicit slot actor attribution and
authority-decision metadata before their corresponding slots can be reported
as available. A surface is complete only when every required slot is backed by
its canonical authority, a registered provider path, evidence/provenance,
freshness, and policy behavior; catalog presence alone does not count.

## See Also

- `docs/product/360s/` — detailed 360 surface documentation
- `docs/architecture/target/360-system-blueprint.md` — 360 system design
